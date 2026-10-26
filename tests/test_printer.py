# SPDX-License-Identifier: AGPL-3.0-only
"""Safety-flow tests. Every scanner, client and send delay is injected and fake."""
import asyncio
from collections import deque
import contextlib
import copy
from dataclasses import replace
import io
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from b21_print.config import Config
from b21_print.printer import Connection, inspect_printer, run_batch
from b21_print.protocol import CHARACTERISTIC, SERVICE


ADDRESS = "00:11:22:33:44:55"  # Deliberately synthetic, not a user's device.
BARCODE = "0000000000000"


def frame(command, data):
    body = bytes((command, len(data))) + data
    checksum = 0
    for byte in body:
        checksum ^= byte
    return b"\x55\x55" + body + bytes((checksum,)) + b"\xaa\xaa"


class FakeScanner:
    def __init__(self, found=True):
        self.calls = []
        self.found = found

    async def find_device_by_address(self, address, timeout):
        self.calls.append((address, timeout))
        return SimpleNamespace(address=ADDRESS) if self.found else None


class FakeClient:
    """Respond synchronously with constructed packets; never touch a BLE library."""
    def __init__(self, device, timeout=20, **options):
        self.device, self.timeout = device, timeout
        self.options = options
        self.char = SimpleNamespace(service_uuid=options.get("service", SERVICE),
                                    max_write_without_response_size=options.get("mtu", 64))
        self.services = self
        self.writes = []
        self.entered = self.closed = self.stopped = False
        self.notify = None
        self.statuses = deque(options.get("statuses", [b"\x00\x01\x64\x64"]))
        self.finishes = deque(options.get("finishes", [b"\x01"]))
        self.status_requested = asyncio.Event()

    def get_characteristic(self, uuid):
        if uuid != CHARACTERISTIC:
            raise AssertionError("Unexpected characteristic")
        return None if self.options.get("missing_char") else self.char

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def start_notify(self, char, callback):
        if self.options.get("notify_error"):
            raise RuntimeError("synthetic notify failure")
        self.notify = callback

    async def stop_notify(self, char):
        self.stopped = True

    async def write_gatt_char(self, char, raw, response=False):
        if response:
            raise AssertionError("Unexpected write-with-response")
        raw = raw[1:] if raw.startswith(b"\x03\x55\x55") else raw
        command, payload = raw[2], raw[4:-3]
        self.writes.append((command, payload))
        if command == 0xA3:
            self.status_requested.set()
        if command == self.options.get("raise_on"):
            raise RuntimeError("synthetic write failure")
        if command == self.options.get("cancel_on"):
            raise asyncio.CancelledError()
        if command == self.options.get("drop_on"):
            return
        if command == self.options.get("error_on"):
            self.notify(None, frame(0xDB, b"\x07"))
            return
        if command in (0x84, 0x85, 0xDA):
            return
        heartbeat = bytearray(13)
        heartbeat[9] = self.options.get("lid", 0)
        heartbeat[11] = self.options.get("paper", 0)
        heartbeat[12] = self.options.get("rfid", 1)
        info = bytes(4) + b"\x01\x80\x02" + bytes(3)
        barcode = self.options.get("barcode", BARCODE).encode("ascii")
        replies = {
            0xC1: (0xC2, self.options.get("handshake", b"\x01")),
            0xA5: (0xB5, b"\x01"),
            0x40: (0x48, self.options.get("model", 771).to_bytes(2, "big")),
            0x1A: (0x1B, self.options.get("paper_data", bytes(8) + bytes((len(barcode),)) + barcode)),
            0x21: (0x31, b"\x01"), 0x23: (0x33, b"\x01"),
            0x01: (0x02, b"\x01"), 0x03: (0x04, b"\x01"),
            0x13: (0x14, b"\x01\x00"), 0xE3: (0xE4, b"\x01"),
        }
        if command == 0xDC:
            reply = ((0xDE, self.options.get("info", info)) if payload == b"\x03"
                     else (0xDD, self.options.get("heartbeat", bytes(heartbeat))))
        elif command == 0xA3:
            reply = (0xB3, self.statuses.popleft() if self.statuses else b"\x00\x01\x64\x64")
        elif command == 0xF3:
            reply = (0xF4, self.finishes.popleft() if self.finishes else b"\x01")
        else:
            reply = replies[command]
        code, data = reply
        if command == self.options.get("reject_on"):
            data = b"\x00"
        self.notify(None, frame(code, data))


class Rig:
    def __init__(self, **options):
        self.per_client = options.pop("per_client", [])
        self.options = options
        self.scanner = FakeScanner()
        self.clients, self.connections, self.delays = [], [], []

    async def sleep(self, seconds):
        self.delays.append(seconds)
        await asyncio.sleep(0)  # Yield for cancellation/timeouts; never actually delay.

    def client(self, device, timeout):
        options = dict(self.options)
        if len(self.clients) < len(self.per_client):
            options.update(self.per_client[len(self.clients)])
        client = FakeClient(device, timeout, **options)
        self.clients.append(client)
        return client

    def connection(self, config):
        class FastConnection(Connection):
            async def request(self, command, expected, data=b"\x01", timeout=4):
                return await super().request(command, expected, data, min(timeout, 0.03))
        connection = FastConnection(config, self.scanner, self.client, self.sleep)
        self.connections.append(connection)
        return connection


class PrinterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Even if bleak happens to be installed, accidental real-hardware imports fail.
        hardware_barrier = patch.dict(sys.modules, {"bleak": None})
        hardware_barrier.start()
        self.addCleanup(hardware_barrier.stop)
        self.config = replace(Config(), address=ADDRESS, expected_barcode=BARCODE, end=2)
        self.image = Image.new("1", (320, 160), 255)
        self.job = {"state": "preflight", "confirmed_numbers": []}
        self.snapshots = []

    def save(self):
        self.snapshots.append(copy.deepcopy(self.job))

    async def batch(self, rig):
        with contextlib.redirect_stdout(io.StringIO()):
            await run_batch(self.config, [self.image, self.image], self.job, self.save,
                            rig.connection, rig.sleep)

    async def test_every_label_has_fresh_connection_confirmed_status_and_end(self):
        rig = Rig(statuses=[b"\x00\x00\x64\x64", b"\x00\x01\x63\x64",
                            b"\x00\x01\x64\x64"], finishes=[b"\x00", b"\x01"])
        await self.batch(rig)
        self.assertEqual(self.job["confirmed_numbers"], [1, 2])
        self.assertEqual(self.job["state"], "completed")
        self.assertIsNone(self.job["current_number"])
        self.assertEqual(len(rig.clients), 2)
        self.assertIsNot(rig.clients[0], rig.clients[1])
        self.assertIsNot(rig.connections[0].receiver, rig.connections[1].receiver)
        self.assertEqual(rig.scanner.calls, [(ADDRESS, 10), (ADDRESS, 10)])
        self.assertIn(1.0, rig.delays)
        for client in rig.clients:
            self.assertTrue(client.entered and client.closed and client.stopped)
            commands = [command for command, _ in client.writes]
            self.assertEqual(commands.count(0x01), 1)
            self.assertEqual(commands.count(0xA3), 3)
            self.assertEqual(commands.count(0xF3), 2)
            self.assertNotIn(0xDA, commands)
        for snapshot in self.snapshots:
            if snapshot["state"] in ("starting", "printing"):
                self.assertNotIn(snapshot["current_number"], snapshot["confirmed_numbers"])

    async def test_inspect_accepts_only_tested_models_and_optional_handshake(self):
        for model in (771, 775):
            rig = Rig(model=model, handshake=b"\x03")
            status = await inspect_printer(self.config, rig.connection)
            self.assertEqual(status, {"model_id": model, "printhead_dots": 384, "dpi": 203,
                                      "lid_closed": True, "paper_inserted": True,
                                      "rfid_ok": True, "paper_barcode": BARCODE})
            self.assertIn(0xA5, [command for command, _ in rig.clients[0].writes])

    async def test_unknown_model_printhead_status_or_handshake_prevents_print_start(self):
        bad = [dict(model=1), dict(handshake=b"\x00"), dict(info=bytes(10)),
               dict(info=bytes(9)), dict(heartbeat=bytes(12)), dict(paper_data=bytes(9))]
        for options in bad:
            with self.subTest(options=options):
                rig = Rig(**options)
                with self.assertRaises((RuntimeError, ValueError)):
                    await self.batch(rig)
                self.assertEqual(len(rig.clients), 1)
                self.assertFalse(self.job["confirmed_numbers"])
                self.assertNotIn(0x01, [command for command, _ in rig.clients[0].writes])
                self.assertTrue(rig.clients[0].closed)

    async def test_paper_lid_rfid_and_barcode_guard_before_any_print_command(self):
        for options in (dict(lid=1), dict(paper=1), dict(rfid=0), dict(barcode="1111111111111")):
            with self.subTest(options=options):
                rig = Rig(**options)
                with self.assertRaises(RuntimeError):
                    await self.batch(rig)
                commands = [command for command, _ in rig.clients[0].writes]
                self.assertNotIn(0x21, commands)
                self.assertNotIn(0x01, commands)
                self.assertNotIn(0xDA, commands)
                self.assertFalse(self.job["confirmed_numbers"])

    async def test_mtu_preflight_refuses_before_start(self):
        rig = Rig(mtu=50)  # 46-byte raster payload needs a 53-byte packet.
        image = Image.new("1", (320, 160), 0)
        async with rig.connection(self.config) as connection:
            with self.assertRaisesRegex(RuntimeError, "未开始打印"):
                await connection.print_one(image, self.job, self.save)
        self.assertNotIn(0x01, [command for command, _ in rig.clients[0].writes])

    async def test_rejected_start_timeout_write_and_device_error_stop_no_retry(self):
        for options in (dict(reject_on=0x01), dict(drop_on=0x01), dict(raise_on=0xE3),
                        dict(error_on=0xA3), dict(statuses=[b"\x00\x02\x64\x64"]),
                        dict(drop_on=0xF3)):
            with self.subTest(options=options):
                self.job = {"state": "preflight", "confirmed_numbers": []}
                rig = Rig(**options)
                with self.assertRaises((RuntimeError, TimeoutError)):
                    await self.batch(rig)
                self.assertEqual(len(rig.clients), 1)
                commands = [command for command, _ in rig.clients[0].writes]
                self.assertEqual(commands.count(0x01), 1)
                self.assertEqual(commands.count(0xDA), 1)
                self.assertTrue(self.job["cancel_sent"])
                self.assertFalse(self.job["confirmed_numbers"])
                self.assertTrue(rig.clients[0].closed and rig.clients[0].stopped)

    async def test_failure_on_second_label_preserves_only_first_confirmation(self):
        rig = Rig(per_client=[{}, {"reject_on": 0x01}])
        with self.assertRaises(RuntimeError):
            await self.batch(rig)
        self.assertEqual(len(rig.clients), 2)
        self.assertEqual(self.job["confirmed_numbers"], [1])
        self.assertEqual(self.job["current_number"], 2)
        self.assertNotEqual(self.job["state"], "completed")
        self.assertTrue(all(client.closed for client in rig.clients))
        first_commands = [c for c, _ in rig.clients[0].writes]
        second_commands = [c for c, _ in rig.clients[1].writes]
        self.assertNotIn(0xDA, first_commands)
        self.assertEqual(second_commands.count(0x01), 1)
        self.assertEqual(second_commands.count(0xDA), 1)

    async def test_rejected_density_stops_without_start_or_cancellation(self):
        rig = Rig(reject_on=0x21)
        with self.assertRaises(RuntimeError):
            await self.batch(rig)
        commands = [command for command, _ in rig.clients[0].writes]
        self.assertNotIn(0x01, commands)
        self.assertNotIn(0xDA, commands)
        self.assertEqual(len(rig.clients), 1)

    async def test_task_cancellation_attempts_cancel_and_closes_without_confirming(self):
        rig = Rig(drop_on=0xA3)
        task = asyncio.create_task(self.batch(rig))
        # Wait using scheduler yields only; the fake client signals the exact boundary.
        while not rig.clients:
            await asyncio.sleep(0)
        await rig.clients[0].status_requested.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(rig.clients), 1)
        self.assertTrue(self.job["cancel_sent"])
        self.assertFalse(self.job["confirmed_numbers"])
        self.assertTrue(rig.clients[0].closed)
        self.assertEqual([c for c, _ in rig.clients[0].writes].count(0xDA), 1)

    async def test_failed_best_effort_cancel_preserves_original_error(self):
        rig = Rig(reject_on=0x01, raise_on=0xDA)
        with self.assertRaisesRegex(RuntimeError, "被拒绝"):
            await self.batch(rig)
        self.assertFalse(self.job["cancel_sent"])
        self.assertEqual(len(rig.clients), 1)

    async def test_missing_device_or_bad_service_closes_without_printing(self):
        rig = Rig()
        rig.scanner.found = False
        with self.assertRaisesRegex(RuntimeError, "未发现"):
            async with rig.connection(self.config):
                self.fail("Must not connect")
        self.assertFalse(rig.clients)
        for options in (dict(missing_char=True), dict(service="synthetic-wrong-service"),
                        dict(notify_error=True)):
            with self.subTest(options=options):
                rig = Rig(**options)
                with self.assertRaises(RuntimeError):
                    async with rig.connection(self.config):
                        self.fail("Must not enter invalid connection")
                self.assertTrue(rig.clients[0].closed)
                self.assertFalse(rig.clients[0].writes)

    async def test_invalid_batch_or_missing_identity_never_creates_connection(self):
        rig = Rig()
        with self.assertRaises(ValueError):
            await run_batch(self.config, [self.image], self.job, self.save, rig.connection, rig.sleep)
        with self.assertRaises(ValueError):
            await run_batch(replace(self.config, address=""), [self.image] * 2,
                            self.job, self.save, rig.connection, rig.sleep)
        with self.assertRaises(ValueError):
            await inspect_printer(replace(self.config, address=""), rig.connection)
        self.assertFalse(rig.connections)

    async def test_request_ignores_unrelated_responses_and_discards_stale_queue(self):
        rig = Rig()
        async with rig.connection(self.config) as connection:
            connection.receiver.queue.put_nowait((0x31, b"stale"))
            original = connection.client.write_gatt_char
            async def write(char, raw, response=False):
                connection.receiver.notify(None, frame(0x33, b"unrelated"))
                await original(char, raw, response=response)
            connection.client.write_gatt_char = write
            self.assertEqual(await connection.request(0x21, 0x31), b"\x01")

    async def test_send_checks_write_limit_and_sticky_errors_before_writing(self):
        rig = Rig(mtu=8)
        async with rig.connection(self.config) as connection:
            with self.assertRaisesRegex(RuntimeError, "写入上限"):
                await connection.send(0x13, bytes(6))
            connection.receiver.notify(None, frame(0xDB, b"\x07"))
            with self.assertRaisesRegex(RuntimeError, "错误代码"):
                await connection.send(0x21)
        self.assertFalse(rig.clients[0].writes)


if __name__ == "__main__":
    unittest.main()
