# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 HosisoraLing and contributors
"""Validated local configuration; no device identity is built into the program."""
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import json


@dataclass(frozen=True)
class Config:
    address: str = ""
    expected_barcode: str = ""
    name: str = "计算服务器"
    prefix: str = "X"
    start: int = 1
    end: int = 28
    digits: int = 3
    width_mm: int = 40
    height_mm: int = 20
    density: int = 3
    font_path: str = ""
    font_size: int = 29
    number_font_size: int = 32
    margin_x_mm: float = 2.5
    margin_y_mm: float = 2.0
    line_dots: int = 2
    cell_padding_dots: int = 6

    def validate(self, printing=False):
        for key in ("start", "end", "digits", "width_mm", "height_mm", "density",
                    "font_size", "number_font_size", "line_dots", "cell_padding_dots"):
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} 必须为整数")
        for key in ("address", "expected_barcode", "name", "prefix", "font_path"):
            if not isinstance(getattr(self, key), str):
                raise ValueError(f"{key} 必须为文本")
        if not 1 <= self.start <= self.end <= 999999 or self.end-self.start+1 > 500:
            raise ValueError("编号须为 1..999999，单批最多 500 张")
        if not 1 <= self.digits <= 6 or self.end >= 10**self.digits:
            raise ValueError("digits 须为 1..6 且能容纳编号")
        # Keep the tested profile explicit instead of claiming untested paper sizes.
        if (self.width_mm, self.height_mm) != (40, 20):
            raise ValueError("当前仅支持已测试的 40×20 mm 标签")
        if not 1 <= self.density <= 5:
            raise ValueError("density 须为 1..5")
        if not 8 <= self.font_size <= 48 or not 8 <= self.number_font_size <= 48:
            raise ValueError("字体点数须为 8..48")
        if not 1 <= self.line_dots <= 4 or not 3 <= self.cell_padding_dots <= 16:
            raise ValueError("边框须为 1..4 点，单元格留白须为 3..16 点")
        if self.cell_padding_dots <= self.line_dots:
            raise ValueError("单元格留白须大于边框厚度")
        for key in ("margin_x_mm", "margin_y_mm"):
            value = getattr(self, key)
            if type(value) not in (int, float) or not 1 <= value <= 4:
                raise ValueError(f"{key} 须为 1..4 毫米")
        if not self.name.strip() or len(self.name) > 40 or len(self.prefix) > 12:
            raise ValueError("名称不能为空或超过 40 字，前缀不能超过 12 字")
        if any(ord(c) < 32 for c in self.name+self.prefix):
            raise ValueError("名称和前缀不能包含控制字符")
        if self.expected_barcode and (not self.expected_barcode.isascii() or not self.expected_barcode.isdigit()):
            raise ValueError("expected_barcode 应为纸卷商品条码数字")
        if printing and (not self.address.strip() or not self.expected_barcode):
            raise ValueError("实际打印必须设置 address 和 expected_barcode；先 scan / inspect 核实")
        return self

    def label(self, number):
        return f"{self.prefix}{number:0{self.digits}d}"

    def public_job_spec(self):
        # No BLE address, font path, raw RFID or paper serial in saved task records.
        return {k: v for k, v in asdict(self).items()
                if k not in {"address", "font_path", "expected_barcode"}}


def load_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("配置根节点必须是对象")
    unknown = set(data)-{field.name for field in fields(Config)}
    if unknown:
        raise ValueError("未知配置项："+", ".join(sorted(unknown)))
    return Config(**data).validate()
