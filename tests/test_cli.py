# SPDX-License-Identifier: AGPL-3.0-only
"""CLI tests run behind an import barrier or a wholly fake printer module."""
import builtins
import contextlib
from dataclasses import asdict
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
from b21_print import cli
from b21_print.config import Config


@contextlib.contextmanager
def forbid_hardware_imports():
    original = builtins.__import__
    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("printer", "b21_print.printer", "bleak") or name.startswith("bleak."):
            raise AssertionError("Hardware import forbidden in offline path: " + name)
        return original(name, globals, locals, fromlist, level)
    with patch("builtins.__import__", side_effect=guarded):
        yield


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.json"
        self.out = self.root / "output"
        self.write_config()
        self.image = Image.new("1", (320, 160), 255)

    def write_config(self, **updates):
        data = asdict(Config())
        data.update(start=1, end=2)
        data.update(updates)
        self.config.write_text(json.dumps(data), encoding="utf-8")

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli.main(list(args))
        return result, output.getvalue()

    def args(self, *extra):
        return ("print", "--config", str(self.config), "--out", str(self.out), *extra)

    @contextlib.contextmanager
    def fake_printer(self):
        fake = ModuleType("b21_print.printer")
        fake.run_batch = AsyncMock()
        fake.scan_devices = AsyncMock(return_value=[{"name": "B21-TEST", "address": "00:11:22:33:44:55"}])
        fake.inspect_printer = AsyncMock(return_value={"paper_barcode": "0000000000000"})
        with patch.dict(sys.modules, {"b21_print.printer": fake}):
            yield fake

    def test_cli_module_import_never_imports_hardware(self):
        spec = importlib.util.spec_from_file_location("b21_print._offline_cli_test", cli.__file__)
        module = importlib.util.module_from_spec(spec)
        with forbid_hardware_imports():
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))

    def test_print_without_execute_is_offline_and_creates_no_job(self):
        with forbid_hardware_imports(), patch.object(cli, "make_label", return_value=self.image) as render:
            result, output = self.invoke(*self.args())
        self.assertEqual(result, 0)
        self.assertEqual(render.call_count, 2)
        self.assertIn("没有连接打印机、没有出纸", output)
        self.assertFalse(self.out.exists())

    def test_confirm_size_without_execute_is_still_dry_run(self):
        with forbid_hardware_imports(), patch.object(cli, "make_label", return_value=self.image):
            result, _ = self.invoke(*self.args("--confirm-paper-size"))
        self.assertEqual(result, 0)
        self.assertFalse(self.out.exists())

    def test_execute_without_explicit_size_confirmation_refuses_before_import(self):
        self.write_config(address="00:11:22:33:44:55", expected_barcode="0000000000000")
        with forbid_hardware_imports(), patch.object(cli, "make_label", return_value=self.image):
            result, output = self.invoke(*self.args("--execute"))
        self.assertEqual(result, 1)
        self.assertIn("--confirm-paper-size", output)
        self.assertFalse(self.out.exists())

    def test_execute_without_identity_refuses_before_import(self):
        with forbid_hardware_imports(), patch.object(cli, "make_label", return_value=self.image):
            result, output = self.invoke(*self.args("--execute", "--confirm-paper-size"))
        self.assertEqual(result, 1)
        self.assertIn("address", output)
        self.assertFalse(self.out.exists())

    def test_every_image_validated_before_any_hardware_import_or_job(self):
        for effects in ([self.image, ValueError("synthetic render failure")],
                        [self.image, Image.new("RGB", (320, 160))]):
            with self.subTest(effects=effects), forbid_hardware_imports():
                with patch.object(cli, "make_label", side_effect=effects):
                    result, _ = self.invoke(*self.args("--execute", "--confirm-paper-size"))
                self.assertEqual(result, 1)
                self.assertFalse(self.out.exists())

    def test_preview_is_offline_and_applies_range_override(self):
        with forbid_hardware_imports(), patch.object(cli, "generate", return_value=1) as generate:
            result, _ = self.invoke("preview", "--config", str(self.config), "--start", "2", "--end", "2")
        self.assertEqual(result, 0)
        self.assertEqual((generate.call_args.args[0].start, generate.call_args.args[0].end), (2, 2))

    def test_invalid_config_and_range_refuse_before_render(self):
        for updates, extra in (({"unknown_setting": 1}, ()), ({}, ("--start", "3", "--end", "2"))):
            self.write_config(**updates)
            with forbid_hardware_imports(), patch.object(cli, "make_label") as render:
                result, _ = self.invoke(*self.args(*extra))
            self.assertEqual(result, 1)
            render.assert_not_called()

    def test_init_creates_identity_free_config_and_never_overwrites(self):
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            # Existing local configuration must survive byte-for-byte.
            before = self.config.read_bytes()
            with forbid_hardware_imports():
                self.assertEqual(self.invoke("init")[0], 1)
            self.assertEqual(self.config.read_bytes(), before)
            new_directory = self.root / "fresh"
            new_directory.mkdir()
            os.chdir(new_directory)
            with forbid_hardware_imports():
                self.assertEqual(self.invoke("init")[0], 0)
            created = json.loads((new_directory / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(created["address"], "")
            self.assertEqual(created["expected_barcode"], "")
            self.assertEqual(created["end"], 28)
        finally:
            os.chdir(previous)

    def test_license_and_help_work_without_config_or_hardware(self):
        with forbid_hardware_imports():
            result, output = self.invoke("--license")
            self.assertEqual(result, 0)
            self.assertIn("AGPL-3.0-only", output)
            self.assertIn("无任何担保", output)
            self.assertIn(cli.SOURCE, output)
            self.assertEqual(self.invoke()[0], 0)

    def test_scan_and_inspect_are_mocked_not_bluetooth(self):
        with self.fake_printer() as fake:
            self.assertEqual(self.invoke("scan")[0], 0)
            result, output = self.invoke("inspect", "--config", str(self.config))
            self.assertEqual(result, 0)
            self.assertIn("条码不等于尺寸", output)
            fake.scan_devices.assert_awaited_once()
            fake.inspect_printer.assert_awaited_once()
            fake.run_batch.assert_not_awaited()

    def test_execute_uses_mock_and_identity_free_journal(self):
        self.write_config(address="00:11:22:33:44:55", expected_barcode="0000000000000", font_path="test-only.ttf")
        async def complete(config, images, job, save):
            self.assertEqual(len(images), 2)
            job.update(state="completed", confirmed_numbers=[1, 2])
            save()
        with self.fake_printer() as fake, patch.object(cli, "make_label", return_value=self.image):
            fake.run_batch.side_effect = complete
            result, _ = self.invoke(*self.args("--execute", "--confirm-paper-size"))
            fake.run_batch.assert_awaited_once()
        self.assertEqual(result, 0)
        journals = list((self.out / "jobs").glob("*.json"))
        self.assertEqual(len(journals), 1)
        text = journals[0].read_text(encoding="utf-8")
        job = json.loads(text)
        self.assertEqual(job["state"], "completed")
        self.assertEqual(job["confirmed_numbers"], [1, 2])
        for value in ("00:11:22:33:44:55", "0000000000000", "test-only.ttf"):
            self.assertNotIn(value, text)
        self.assertTrue({"address", "expected_barcode", "font_path"}.isdisjoint(job["spec"]))
        self.assertFalse(list((self.out / "jobs").glob("*.tmp")))

    def test_execute_failure_records_uncertainty_and_error_type_not_exception_detail(self):
        self.write_config(address="00:11:22:33:44:55", expected_barcode="0000000000000")
        with self.fake_printer() as fake, patch.object(cli, "make_label", return_value=self.image):
            fake.run_batch.side_effect = TimeoutError("synthetic detail must not be journaled")
            result, _ = self.invoke(*self.args("--execute", "--confirm-paper-size"))
            fake.run_batch.assert_awaited_once()
        self.assertEqual(result, 1)
        journals = list((self.out / "jobs").glob("*.json"))
        self.assertEqual(len(journals), 1)
        text = journals[0].read_text(encoding="utf-8")
        job = json.loads(text)
        self.assertEqual(job["state"], "failed_or_uncertain")
        self.assertEqual(job["error_type"], "TimeoutError")
        self.assertEqual(job["confirmed_numbers"], [])
        self.assertNotIn("synthetic detail", text)


if __name__ == "__main__":
    unittest.main()
