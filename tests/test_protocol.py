# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic protocol fixtures only: no captured printer/device responses."""
import struct
import unittest
from PIL import Image
from b21_print.protocol import (Receiver, accepted_ack, image_commands, packet,
                                paper_barcode, print_status)


def response_frame(command, payload=b"\x01"):
    """Build an independent synthetic response, including commands not send-allowed."""
    body = bytes((command, len(payload))) + payload
    checksum = 0
    for value in body:
        checksum ^= value
    return b"\x55\x55" + body + bytes((checksum,)) + b"\xaa\xaa"


class PacketTests(unittest.TestCase):
    def test_known_xor_checksum_and_handshake_prefix(self):
        self.assertEqual(packet(0x21, b"\x03"), bytes.fromhex("55 55 21 01 03 23 aa aa"))
        self.assertEqual(packet(0xC1), bytes.fromhex("03 55 55 c1 01 01 c1 aa aa"))
        # This wire protocol calls its XOR check CRC; it is not polynomial CRC-16.
        for command, data in ((0x13, b"\x00\xa0\x01\x40\x00\x01"), (0x85, bytes(range(46)))):
            raw = packet(command, data)
            checksum = 0
            for value in raw[2:-2]:
                checksum ^= value
            self.assertEqual(checksum, 0)

    def test_unknown_or_firmware_command_and_invalid_payload_length_rejected(self):
        for command, data in ((0, b"\x01"), (0xFF, b"\x01"), (0x21, b""),
                              (0x21, b"x" * 256)):
            with self.subTest(command=command, length=len(data)), self.assertRaises(ValueError):
                packet(command, data)
        self.assertEqual(len(packet(0x85, b"x" * 255)), 262)

    def test_ack_values_are_strict_with_only_documented_page_exception(self):
        self.assertTrue(accepted_ack(0x21, b"\x01"))
        self.assertTrue(accepted_ack(0x13, b"\x01\x00"))
        for command, value in ((0x21, b"\x01\x00"), (0x13, b"\x00"),
                               (0x01, b""), (0x13, b"\x01\x01")):
            with self.subTest(command=command, value=value):
                self.assertFalse(accepted_ack(command, value))


class ReceiverTests(unittest.TestCase):
    def test_every_split_point_and_bytewise_notifications(self):
        raw = response_frame(0xB3, b"\x00\x01\x64\x64")
        for split in range(len(raw) + 1):
            receiver = Receiver()
            receiver.notify(None, raw[:split])
            receiver.notify(None, raw[split:])
            with self.subTest(split=split):
                self.assertEqual(receiver.queue.get_nowait(), (0xB3, b"\x00\x01\x64\x64"))
                self.assertEqual(receiver.buffer, b"")
        receiver = Receiver()
        for value in raw:
            receiver.notify(None, bytes((value,)))
        self.assertEqual(receiver.queue.get_nowait()[0], 0xB3)

    def test_glued_frames_noise_and_partial_header(self):
        receiver = Receiver()
        receiver.notify(None, b"synthetic noise" + b"\x55")
        receiver.notify(None, response_frame(0x31)[1:] + response_frame(0x33, b"\x02"))
        self.assertEqual(receiver.queue.get_nowait(), (0x31, b"\x01"))
        self.assertEqual(receiver.queue.get_nowait(), (0x33, b"\x02"))
        self.assertTrue(receiver.queue.empty())

    def test_corrupt_checksum_and_trailer_resynchronize_to_next_valid_frame(self):
        good = response_frame(0x31)
        bad_crc = bytearray(good)
        bad_crc[-3] ^= 0x40
        bad_trailer = good[:-2] + b"\x00\x00"
        receiver = Receiver()
        receiver.notify(None, b"\x99" + bad_crc + bad_trailer + good)
        self.assertEqual(receiver.queue.get_nowait(), (0x31, b"\x01"))
        self.assertTrue(receiver.queue.empty())
        receiver.check()

    def test_corrupt_large_length_is_not_guessed_and_waits_for_request_timeout(self):
        """Do not invent ACKs by scanning inside a potentially legitimate payload."""
        receiver = Receiver()
        good = response_frame(0x31)
        receiver.notify(None, b"\x55\x55\x31\xff\x00\x00\x00" + good)
        self.assertTrue(receiver.queue.empty())
        self.assertLess(len(receiver.buffer), 262)
        # Connection.request's timeout, covered in test_printer, stops the job.
        receiver.check()

    def test_nested_frame_inside_fragmented_payload_is_not_a_false_ack(self):
        receiver = Receiver()
        payload = b"synthetic" + response_frame(0x31) + b"tail"
        outer = response_frame(0xDE, payload)
        receiver.notify(None, outer[:-4])
        self.assertTrue(receiver.queue.empty())
        receiver.notify(None, outer[-4:])
        self.assertEqual(receiver.queue.get_nowait(), (0xDE, payload))
        self.assertTrue(receiver.queue.empty())

    def test_error_frames_are_sticky_and_empty_error_is_safe(self):
        for command, payload in ((0xDB, b"\x07"), (0xDB, b""), (0, b"\x01")):
            receiver = Receiver()
            receiver.notify(None, response_frame(command, payload))
            receiver.notify(None, response_frame(0x31))
            with self.subTest(command=command, payload=payload):
                for _ in range(2):
                    with self.assertRaises(RuntimeError):
                        receiver.check()

    def test_response_queue_is_bounded_and_overflow_stops_operation(self):
        receiver = Receiver()
        receiver.notify(None, response_frame(0x31) * 129)
        self.assertEqual(receiver.queue.qsize(), 128)
        with self.assertRaisesRegex(RuntimeError, "溢出"):
            receiver.check()


class ImageEncodingTests(unittest.TestCase):
    def decode(self, commands):
        """Independent wire decoder, validating row positions and black-bit counts."""
        image = Image.new("1", (320, 160), 255)
        next_row = 0
        for command, payload in commands:
            row = int.from_bytes(payload[:2], "big")
            self.assertEqual(row, next_row)
            if command == 0x84:
                self.assertEqual(len(payload), 3)
                repeat, data = payload[2], bytes(40)
            else:
                self.assertEqual(command, 0x85)
                self.assertEqual(len(payload), 46)
                repeat, data = payload[5], payload[6:]
                padded = data + bytes(8)
                self.assertEqual(payload[2:5], bytes(sum(v.bit_count() for v in padded[i:i + 16])
                                                   for i in (0, 16, 32)))
            self.assertGreater(repeat, 0)
            self.assertLessEqual(row + repeat, 160)
            for y in range(row, row + repeat):
                for x in range(320):
                    if data[x // 8] & (1 << (7 - x % 8)):
                        image.putpixel((x, y), 0)
            next_row += repeat
        self.assertEqual(next_row, 160)
        return image

    def test_white_rows_collapse_to_one_run(self):
        image = Image.new("1", (320, 160), 255)
        commands = list(image_commands(image))
        self.assertEqual(commands, [(0x84, b"\x00\x00\xa0")])
        self.assertEqual(self.decode(commands).tobytes(), image.tobytes())

    def test_black_rows_collapse_and_counts_are_correct(self):
        image = Image.new("1", (320, 160), 0)
        commands = list(image_commands(image))
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][1][:6], bytes((0, 0, 128, 128, 64, 160)))
        self.assertEqual(self.decode(commands).tobytes(), image.tobytes())

    def test_mixed_bit_boundaries_repeated_rows_and_white_runs_round_trip(self):
        image = Image.new("1", (320, 160), 255)
        for y in range(4, 8):
            for x in (0, 7, 8, 127, 128, 255, 256, 319):
                image.putpixel((x, y), 0)
        for y in range(12, 159):
            for x in range(y % 7, 320, 13):
                image.putpixel((x, y), 0)
        commands = list(image_commands(image))
        self.assertEqual(commands[0], (0x84, struct.pack(">HB", 0, 4)))
        self.assertEqual(commands[1][1][5], 4)
        self.assertEqual(self.decode(commands).tobytes(), image.tobytes())

    def test_wrong_mode_or_dimensions_rejected_before_encoding(self):
        for mode, size in (("L", (320, 160)), ("RGB", (320, 160)),
                           ("1", (160, 320)), ("1", (319, 160))):
            with self.subTest(mode=mode, size=size), self.assertRaises(ValueError):
                list(image_commands(Image.new(mode, size)))


class PaperAndPageTests(unittest.TestCase):
    def test_paper_barcode_extracts_only_synthetic_product_code(self):
        barcode = b"0000000000000"
        raw = bytes(8) + bytes((len(barcode),)) + barcode + b"unused synthetic tail"
        self.assertEqual(paper_barcode(raw), barcode.decode("ascii"))
        for data in (b"", bytes(8), bytes(9), bytes(8) + b"\x0d000"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                paper_barcode(data)
        with self.assertRaises(UnicodeDecodeError):
            paper_barcode(bytes(8) + b"\x01\xff")

    def test_unknown_page_status_layouts_are_not_treated_as_completed(self):
        # Only the confirmed 4/8/10-byte layouts are supported, never guess others.
        for length in (0, 1, 2, 3, 5, 6, 7, 9, 11, 12, 20, 255):
            data = (b"\x00\x01\x64\x64" + bytes(255))[:length]
            with self.subTest(length=length), self.assertRaises(ValueError):
                print_status(data)

    def test_only_page_one_and_both_100_percent_confirm_completion(self):
        self.assertTrue(print_status(b"\x00\x01\x64\x64"))
        self.assertTrue(print_status(b"\x00\x01\x64\x64" + bytes(4)))
        self.assertTrue(print_status(b"\x00\x01\x64\x64" + bytes(6)))
        for data in (b"\x00\x00\x64\x64", b"\x00\x01\x63\x64",
                     b"\x00\x01\x64\x63", b"\x00\x01\x00\x00"):
            with self.subTest(data=data):
                self.assertFalse(print_status(data))
        for data in (b"", b"\x00\x01\x64"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                print_status(data)
        with self.assertRaisesRegex(RuntimeError, "页数"):
            print_status(b"\x00\x02\x64\x64")
        with self.assertRaisesRegex(RuntimeError, "错误代码"):
            print_status(b"\x00\x01\x64\x64\x00\x00\x07\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
