# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 HosisoraLing and contributors
"""No printer traffic on import, preview or dry-run. Explicit execution required."""
import argparse
import asyncio
from dataclasses import asdict,replace
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import uuid
from . import __version__
from .config import Config,load_config
from .labels import generate,make_label

SOURCE = "https://github.com/HosisoraLing/niimbot-b21-print"
NOTICE = ("精臣 B21 蓝牙打印 — 非官方工具\n"
          "Copyright (C) 2026 HosisoraLing and contributors\n"
          "AGPL-3.0-only；无任何担保。许可证：LICENSE\n"
          f"源码与许可证：{SOURCE}\n")


def parser():
    result = argparse.ArgumentParser(description="本地 B21-C2B 蓝牙标签工具（默认不出纸）")
    result.add_argument("--version",action="version",version=__version__)
    result.add_argument("--license",action="store_true",help="显示许可、无担保与源码位置")
    sub = result.add_subparsers(dest="command")
    sub.add_parser("init",help="创建不含设备身份的本地 config.json")
    sub.add_parser("scan",help="只扫描 B21 蓝牙设备，不打印")
    for command in ("inspect","preview","print"):
        p = sub.add_parser(command)
        p.add_argument("--config",default="config.json")
        if command in ("preview","print"):
            p.add_argument("--start",type=int)
            p.add_argument("--end",type=int)
            p.add_argument("--out",default="output")
        if command == "print":
            p.add_argument("--execute",action="store_true",help="实际打印，缺省只离线检查")
            p.add_argument("--confirm-paper-size",action="store_true",help="确认当前纸卷确为40×20mm")
    return result


def save_json(path,data):
    path = Path(path)
    temp = path.with_name(path.name+".tmp")
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(temp,path)


def configure_console():
    # Windows redirected stdout otherwise defaults to e.g. cp1252 and crashes on
    # Chinese text. Configure at CLI entry, not import; don't mutate test streams.
    if os.name == "nt":
        for stream in (sys.stdout,sys.stderr):
            if hasattr(stream,"reconfigure"):
                stream.reconfigure(encoding="utf-8",errors="backslashreplace")


def main(argv=None):
    configure_console()
    args = parser().parse_args(argv)
    if args.license:
        print(NOTICE)
        return 0
    if not args.command:
        parser().print_help()
        return 0
    try:
        if args.command == "init":
            # Exclusive create: never silently replace local device configuration.
            with Path("config.json").open("x",encoding="utf-8") as file:
                json.dump(asdict(Config()),file,ensure_ascii=False,indent=2)
                file.write("\n")
            print("已创建 config.json；先 scan 并填写设备地址，再 inspect 查看纸卷条码")
            return 0
        if args.command == "scan":
            from .printer import scan_devices
            print(json.dumps(asyncio.run(scan_devices()),ensure_ascii=False,indent=2))
            print("扫描结果只显示在本机；分享前请隐藏设备地址和名称。")
            return 0
        config = load_config(args.config)
        if args.command == "inspect":
            from .printer import inspect_printer
            print(json.dumps(asyncio.run(inspect_printer(config)),ensure_ascii=False,indent=2))
            print("纸卷商品条码不等于尺寸；请对照纸卷包装确认40×20mm后填入expected_barcode。")
            return 0
        config = replace(config,
                         start=args.start if args.start is not None else config.start,
                         end=args.end if args.end is not None else config.end).validate()
        if args.command == "preview":
            count = generate(config,args.out)
            print(f"已生成 {count} 张标签与放大预览。没有连接打印机。")
            return 0
        # Render and validate every page before any Bluetooth/physical side effect.
        images = [make_label(config,n) for n in range(config.start,config.end+1)]
        from .protocol import image_commands
        for image in images:
            list(image_commands(image))
        print(f"{config.label(config.start)}～{config.label(config.end)}，{len(images)}张，40×20mm")
        if not args.execute:
            print("离线检查完成，没有连接打印机、没有出纸。实际打印需 --execute --confirm-paper-size。")
            return 0
        if not args.confirm_paper_size:
            raise ValueError("实际打印必须加 --confirm-paper-size，确认当前纸卷确为40×20mm")
        config.validate(printing=True)
        print(NOTICE)
        print("注意：重复运行会重新出纸；失败后先检查实物与任务记录，不要盲目全量重打。",flush=True)
        directory = Path(args.out)/"jobs"
        directory.mkdir(parents=True,exist_ok=True)
        path = directory/(datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:8]+".json")
        job = {"version":__version__,"created":datetime.now().astimezone().isoformat(),
               "spec":config.public_job_spec(),"state":"preflight","confirmed_numbers":[]}
        def save():
            job["updated"] = datetime.now().astimezone().isoformat()
            save_json(path,job)
        save()
        try:
            from .printer import run_batch
            asyncio.run(run_batch(config,images,job,save))
        except BaseException as error:
            job["state"] = "failed_or_uncertain"
            # No raw packets, device identity, roll serial or exception paths in journal.
            job["error_type"] = type(error).__name__
            save()
            raise
        print(f"全部完成：{len(job['confirmed_numbers'])} 张。任务记录位于输出目录的 jobs 中。")
        return 0
    except KeyboardInterrupt:
        print("已中断。若已开始出纸，请先核对实物和任务记录。")
        return 130
    except (ValueError,FileNotFoundError,FileExistsError,RuntimeError,TimeoutError,OSError) as error:
        print(f"操作停止：{error}")
        return 1
