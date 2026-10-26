# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 HosisoraLing and contributors
# Protocol/print-flow references: NiimBlueLib and niimprint (MIT).
# See THIRD_PARTY_NOTICES.md and licenses/ for retained upstream notices.
"""Bounded packet parser and monochrome image encoding. No firmware commands."""
import asyncio
import struct

SERVICE = "e7810a71-73ae-499d-8c15-faa9aef0c3f2"
CHARACTERISTIC = "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"
ALLOWED = {0xC1,0x40,0xA5,0xDC,0x1A,0x21,0x23,0x01,0x03,0x13,0x84,0x85,0xE3,0xA3,0xF3,0xDA}


def packet(command,data=b"\x01"):
    if command not in ALLOWED or not 1 <= len(data) <= 255:
        raise ValueError("Command/payload not allowed")
    body = bytes([command,len(data)])+data
    checksum = 0
    for byte in body:
        checksum ^= byte
    return (b"\x03" if command == 0xC1 else b"")+b"\x55\x55"+body+bytes([checksum])+b"\xaa\xaa"


def accepted_ack(command,value):
    return value == b"\x01" or (command == 0x13 and value == b"\x01\x00")


class Receiver:
    def __init__(self):
        self.buffer = bytearray()
        self.queue = asyncio.Queue(maxsize=128)
        self.error = None

    def notify(self,_,data):
        self.buffer.extend(data)
        while len(self.buffer) >= 7:
            start = self.buffer.find(b"\x55\x55")
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1:] == b"\x55" else b""
                return
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 7:
                return
            length = self.buffer[3]+7
            if len(self.buffer) < length:
                return
            raw = bytes(self.buffer[:length])
            checksum = 0
            for byte in raw[2:-3]:
                checksum ^= byte
            if raw[-2:] != b"\xaa\xaa" or checksum != raw[-3]:
                del self.buffer[0]
                continue
            del self.buffer[:length]
            command,payload = raw[2],raw[4:-3]
            if command == 0xDB:
                self.error = RuntimeError(f"打印机错误代码 {payload[0] if payload else -1}")
            elif command == 0:
                self.error = RuntimeError("打印机拒绝了不支持的指令")
            if self.queue.full():
                self.error = RuntimeError("蓝牙响应队列溢出，已停止")
                self.queue.get_nowait()
            self.queue.put_nowait((command,payload))

    def check(self):
        if self.error:
            raise self.error


def image_commands(image):
    if image.size != (320,160) or image.mode != "1":
        raise ValueError("Expected monochrome 320×160-dot image")
    rows = []
    for y in range(image.height):
        data = bytearray(40)
        for x in range(image.width):
            if image.getpixel((x,y)) == 0:
                data[x//8] |= 1 << (7-x%8)
        rows.append(bytes(data))
    y = 0
    while y < len(rows):
        data,repeat = rows[y],1
        while y+repeat < len(rows) and rows[y+repeat] == data and repeat < 255:
            repeat += 1
        if not any(data):
            yield 0x84,struct.pack(">HB",y,repeat)
        else:
            padded = data.ljust(48,b"\x00")
            counts = bytes(min(255,sum(b.bit_count() for b in padded[i:i+16])) for i in (0,16,32))
            yield 0x85,struct.pack(">H",y)+counts+bytes([repeat])+data
        y += repeat


def paper_barcode(data):
    # Deliberately do not expose/retain RFID UUID or roll serial number.
    if len(data) < 9 or not data[8] or len(data) < 9+data[8]:
        raise ValueError("纸卷 RFID 信息缺失或损坏")
    return data[9:9+data[8]].decode("ascii")


def print_status(data):
    if len(data) not in (4,8,10):
        raise ValueError("未知或不完整的打印状态布局")
    if len(data) == 10 and data[6]:
        raise RuntimeError(f"打印状态错误代码 {data[6]}")
    page = int.from_bytes(data[:2],"big")
    if page > 1:
        raise RuntimeError("单页任务出现异常页数，已停止")
    return page == 1 and data[2] == 100 and data[3] == 100
