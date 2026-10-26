# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 HosisoraLing and contributors
# Protocol/flow references: MIT-licensed NiimBlueLib and niimprint; see notices.
"""Tested B21-C2B profile; reconnect per label, stop on uncertain results."""
import asyncio
import struct
from .protocol import (SERVICE,CHARACTERISTIC,Receiver,packet,accepted_ack,
                       image_commands,paper_barcode,print_status)


class Connection:
    def __init__(self,config,scanner=None,client_factory=None,sleep=asyncio.sleep):
        self.config = config
        self.scanner = scanner
        self.client_factory = client_factory
        self.sleep = sleep
        self.receiver = Receiver()
        self.client = None
        self.char = None
        self.last_send = 0.0

    async def __aenter__(self):
        if self.scanner is None or self.client_factory is None:
            from bleak import BleakClient,BleakScanner
            self.scanner = self.scanner or BleakScanner
            self.client_factory = self.client_factory or BleakClient
        device = await self.scanner.find_device_by_address(self.config.address,timeout=10)
        if not device:
            raise RuntimeError("未发现指定 B21；请开机并关闭手机 App 的连接")
        self.client = self.client_factory(device,timeout=20)
        await self.client.__aenter__()
        try:
            self.char = self.client.services.get_characteristic(CHARACTERISTIC)
            if self.char is None or self.char.service_uuid != SERVICE:
                raise RuntimeError("未找到预期的 NIIMBOT BLE 通道")
            await self.client.start_notify(self.char,self.receiver.notify)
            return self
        except BaseException:
            await self.client.__aexit__(None,None,None)
            raise

    async def __aexit__(self,*exc):
        try:
            await self.client.stop_notify(self.char)
        finally:
            await self.client.__aexit__(*exc)

    async def send(self,command,data=b"\x01"):
        self.receiver.check()
        await self.sleep(max(0,0.020-(asyncio.get_running_loop().time()-self.last_send)))
        raw = packet(command,data)
        if len(raw) > self.char.max_write_without_response_size:
            raise RuntimeError("BLE 写入上限不足，不会盲目拆分数据包")
        await self.client.write_gatt_char(self.char,raw,response=False)
        self.last_send = asyncio.get_running_loop().time()
        self.receiver.check()

    async def request(self,command,expected,data=b"\x01",timeout=4):
        self.receiver.check()
        while not self.receiver.queue.empty():
            self.receiver.queue.get_nowait()
        await self.send(command,data)
        async with asyncio.timeout(timeout):
            while True:
                code,payload = await self.receiver.queue.get()
                self.receiver.check()
                if code == expected:
                    return payload

    async def ack(self,command,expected,data=b"\x01"):
        result = await self.request(command,expected,data)
        if not accepted_ack(command,result):
            raise RuntimeError(f"指令 0x{command:02x} 被拒绝；停止而不自动重试")

    async def inspect(self):
        connected = await self.request(0xC1,0xC2)
        if connected not in (b"\x01",b"\x02",b"\x03"):
            raise RuntimeError("打印机握手失败")
        if connected == b"\x03":
            await self.request(0xA5,0xB5)
        model = int.from_bytes(await self.request(0x40,0x48,b"\x08"),"big")
        if model not in (771,775):
            raise RuntimeError("仅支持 B21-C2B（型号 ID 771/775）；不会套用其他 B21 固件")
        info = await self.request(0xDC,0xDE,b"\x03")
        if len(info) != 10 or info[4:6] != b"\x01\x80" or info[6] != 2:
            raise RuntimeError("打印头宽度或 DPI 不符合已测试配置")
        heartbeat = await self.request(0xDC,0xDD,b"\x01")
        if len(heartbeat) != 13:
            raise RuntimeError("未知的状态布局；不会猜测设备状态")
        rfid = await self.request(0x1A,0x1B)
        return {"model_id":model,"printhead_dots":384,"dpi":203,
                "lid_closed":heartbeat[9]==0,"paper_inserted":heartbeat[11]==0,
                "rfid_ok":heartbeat[12]==1,"paper_barcode":paper_barcode(rfid)}

    async def print_one(self,image,job,save):
        status = await self.inspect()
        if not all(status[k] for k in ("lid_closed","paper_inserted","rfid_ok")):
            raise RuntimeError("盖子未合、未放纸或纸卷 RFID 未就绪")
        if status["paper_barcode"] != self.config.expected_barcode:
            raise RuntimeError("纸卷商品条码与已确认规格不同；请先核实尺寸")
        commands = list(image_commands(image))
        if any(len(packet(c,d)) > self.char.max_write_without_response_size for c,d in commands):
            raise RuntimeError("BLE 写入上限不足以传输标签；未开始打印")
        await self.ack(0x21,0x31,bytes([self.config.density]))
        await self.ack(0x23,0x33,b"\x01")
        started = False
        try:
            # Set BEFORE transmitting: a lost ACK must not cause a silent retry.
            started = True
            job["state"] = "starting"
            save()
            await self.ack(0x01,0x02,struct.pack(">H",1)+b"\x00"*5)
            job["state"] = "printing"
            save()
            await self.ack(0x03,0x04)
            await self.ack(0x13,0x14,struct.pack(">HHH",160,320,1))
            for command,data in commands:
                await self.send(command,data)
            await self.ack(0xE3,0xE4)
            async with asyncio.timeout(30):
                while True:
                    await self.sleep(0.3)
                    if print_status(await self.request(0xA3,0xB3)):
                        break
            async with asyncio.timeout(15):
                while await self.request(0xF3,0xF4) != b"\x01":
                    await self.sleep(0.3)
            started = False
        except BaseException:
            if started:
                # Best-effort cancellation; no automatic page reprint.
                try:
                    await self.client.write_gatt_char(self.char,packet(0xDA),response=False)
                    job["cancel_sent"] = True
                except Exception:
                    job["cancel_sent"] = False
            raise


async def inspect_printer(config,connection_factory=Connection):
    if not config.address.strip():
        raise ValueError("请先配置 address")
    async with connection_factory(config) as connection:
        return await connection.inspect()


async def run_batch(config,images,job,save,connection_factory=Connection,sleep=asyncio.sleep):
    config.validate(printing=True)
    if len(images) != config.end-config.start+1:
        raise ValueError("标签数量与编号范围不匹配")
    for index,image in enumerate(images):
        if index:
            await sleep(1.0)
        number = config.start+index
        job["current_number"] = number
        job["state"] = "preflight"
        save()
        # A fresh connection per label matches the hardware-tested workaround.
        async with connection_factory(config) as connection:
            await connection.print_one(image,job,save)
            job["confirmed_numbers"].append(number)
            job["state"] = "between_labels"
            save()
        print(f"已确认完成 {config.label(number)}",flush=True)
    job["state"] = "completed"
    job["current_number"] = None
    save()


async def scan_devices():
    from bleak import BleakScanner
    devices = await BleakScanner.discover(timeout=10,return_adv=True)
    return [{"name":adv.local_name or device.name or "","address":device.address}
            for device,adv in devices.values()
            if (adv.local_name or device.name or "").upper().startswith("B21")]
