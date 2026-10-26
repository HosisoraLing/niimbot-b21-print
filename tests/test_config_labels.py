# SPDX-License-Identifier: AGPL-3.0-only
"""Offline validation and rendering tests; use installed fonts, never bundle one."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageFont
from b21_print.config import Config, load_config
from b21_print.labels import generate, make_label, resolve_font


class ConfigTests(unittest.TestCase):
    def test_default_config_and_28_unique_numbers(self):
        config = Config()
        self.assertIs(config.validate(), config)
        numbers = [config.label(n) for n in range(config.start, config.end + 1)]
        self.assertEqual(len(numbers), 28)
        self.assertEqual(len(set(numbers)), 28)
        self.assertEqual((numbers[0], numbers[-1]), ("X001", "X028"))

    def test_integer_fields_reject_bool_float_and_text(self):
        for key in ("start", "end", "digits", "width_mm", "height_mm", "density",
                    "font_size", "number_font_size", "line_dots", "cell_padding_dots"):
            for value in (True, 1.0, "1", None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(Config(), **{key: value}).validate()

    def test_text_fields_reject_non_text(self):
        for key in ("address", "expected_barcode", "name", "prefix", "font_path"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                replace(Config(), **{key: 123}).validate()

    def test_ranges_sizes_and_font_geometry_are_bounded(self):
        invalid = [dict(start=0), dict(start=29), dict(end=1000000),
                   dict(end=501), dict(digits=0), dict(digits=7), dict(digits=1),
                   dict(width_mm=41), dict(height_mm=30), dict(width_mm=20, height_mm=40),
                   dict(density=0), dict(density=6), dict(font_size=7), dict(font_size=49),
                   dict(number_font_size=7), dict(number_font_size=49),
                   dict(line_dots=0), dict(line_dots=5), dict(cell_padding_dots=2),
                   dict(cell_padding_dots=17), dict(cell_padding_dots=3, line_dots=3)]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(Config(), **kwargs).validate()
        for kwargs in (dict(start=1, end=500), dict(start=999999, end=999999, digits=6),
                       dict(density=1), dict(density=5)):
            with self.subTest(valid=kwargs):
                replace(Config(), **kwargs).validate()

    def test_margins_require_finite_numbers_in_range(self):
        for key in ("margin_x_mm", "margin_y_mm"):
            for value in (True, "2", None, 0.9, 4.1, float("inf"), float("nan")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(Config(), **{key: value}).validate()
            for value in (1, 4.0):
                replace(Config(), **{key: value}).validate()

    def test_names_and_prefixes_reject_empty_long_or_control_text(self):
        for kwargs in (dict(name=""), dict(name="  "), dict(name="a" * 41),
                       dict(prefix="a" * 13), dict(name="a\nb"), dict(prefix="x\x00")):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(Config(), **kwargs).validate()

    def test_printing_requires_explicit_identity_and_ascii_barcode(self):
        for kwargs in ({}, dict(address="00:11:22:33:44:55"),
                       dict(expected_barcode="0000000000000"),
                       dict(address=" ", expected_barcode="0000000000000")):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(Config(), **kwargs).validate(printing=True)
        replace(Config(), address="00:11:22:33:44:55",
                expected_barcode="0000000000000").validate(printing=True)
        for value in ("12-34", "１２３", "abc", "123\n"):
            with self.subTest(barcode=value), self.assertRaises(ValueError):
                replace(Config(), expected_barcode=value).validate()

    def test_config_loading_rejects_unknown_and_non_object_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for data in ([1, 2], None, "text", {"unexpected": 1}, {"density": True}):
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(data=data), self.assertRaises(ValueError):
                    load_config(path)
            path.write_text('\ufeff{"start": 2, "end": 3}', encoding="utf-8")
            self.assertEqual(load_config(path).start, 2)

    def test_public_job_spec_omits_device_and_local_paths(self):
        config = replace(Config(), address="00:11:22:33:44:55",
                         expected_barcode="0000000000000", font_path="test-font.ttf")
        public = config.public_job_spec()
        self.assertTrue({"address", "expected_barcode", "font_path"}.isdisjoint(public))
        self.assertEqual(public["end"], 28)


class LabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.font = resolve_font(Config())
            cls.has_cjk_font = True
        except ValueError:
            # Geometry-only fallback: DejaVuSans does not guarantee Chinese glyphs.
            try:
                cls.font = Path(ImageFont.truetype("DejaVuSans.ttf", 12).path)
            except OSError:
                raise unittest.SkipTest("No installed CJK font or DejaVuSans for geometry tests")
            cls.has_cjk_font = False
        cls.config = replace(Config(), font_path=str(cls.font),
                             name="计算服务器" if cls.has_cjk_font else "Server")

    def test_all_28_labels_are_unique_monochrome_and_correct_geometry(self):
        images = [make_label(self.config, n) for n in range(1, 29)]
        self.assertEqual(len({image.tobytes() for image in images}), 28)
        for number, image in enumerate(images, 1):
            with self.subTest(number=number, cjk_font=self.has_cjk_font):
                self.assertEqual(image.size, (320, 160))
                self.assertEqual(image.mode, "1")
                self.assertEqual({value for _, value in image.getcolors()}, {0, 255})
                self.assertEqual(image.getpixel((0, 0)), 255)
                self.assertEqual(image.getpixel((319, 159)), 255)
                self.assertEqual(image.getpixel((20, 16)), 0)
                self.assertEqual(image.getpixel((20, 100)), 0)

    def test_generate_safe_integer_filenames_and_preview(self):
        config = replace(self.config, start=2, end=4, prefix="../X/")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "out"
            self.assertEqual(generate(config, target), 3)
            self.assertEqual({p.name for p in target.iterdir()},
                             {"label-000002.png", "label-000003.png", "label-000004.png", "preview.png"})
            with Image.open(target / "preview.png") as preview:
                self.assertEqual(preview.size, (960, 480))
            for path in target.glob("label-*.png"):
                with Image.open(path) as image:
                    self.assertEqual((image.mode, image.size), ("1", (320, 160)))

    def test_out_of_range_number_is_rejected(self):
        for number in (0, 29):
            with self.subTest(number=number), self.assertRaises(ValueError):
                make_label(self.config, number)

    def test_missing_font_reports_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "字体不存在"):
                resolve_font(replace(Config(), font_path=str(Path(directory) / "missing.ttf")))
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "font_path"):
                resolve_font(Config())

    def test_text_that_cannot_fit_is_not_silently_clipped(self):
        with self.assertRaisesRegex(ValueError, "文字过长"):
            make_label(replace(self.config, name="W" * 40), 1)


if __name__ == "__main__":
    unittest.main()
