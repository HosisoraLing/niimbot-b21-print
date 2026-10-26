# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 HosisoraLing and contributors
"""Original two-row asset label, rasterized at the tested 8 dots/mm profile."""
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .config import Config


def resolve_font(config: Config):
    if config.font_path:
        path = Path(config.font_path).expanduser()
        if not path.is_file():
            raise ValueError("font_path 指定的字体不存在")
        return path
    # OS-provided font is used, never copied into the distribution.
    root = os.environ.get("WINDIR")
    if root:
        candidate = Path(root)/"Fonts"/"msyh.ttc"
        if candidate.is_file():
            return candidate
    raise ValueError("找不到中文字体，请用 font_path 指定本机已安装的中文 TTF/OTF/TTC 字体")


def make_label(config: Config, number: int):
    config.validate()
    if not config.start <= number <= config.end:
        raise ValueError("编号超出配置范围")
    font_path = resolve_font(config)
    width, height, scale = 320, 160, 4
    image = Image.new("L", (width*scale, height*scale), 255)
    draw = ImageDraw.Draw(image)
    x0, y0 = round(config.margin_x_mm*8), round(config.margin_y_mm*8)
    x1, y1 = width-x0-1, height-y0-1
    split_x = x0+round((x1-x0)*0.32)
    split_y = (y0+y1)//2
    line = config.line_dots*scale
    draw.rectangle((x0*scale,y0*scale,x1*scale,y1*scale),outline=0,width=line)
    draw.line((split_x*scale,y0*scale,split_x*scale,y1*scale),fill=0,width=line)
    draw.line((x0*scale,split_y*scale,x1*scale,split_y*scale),fill=0,width=line)

    def center(text,box,target_size):
        xa,ya,xb,yb = [v*scale for v in box]
        max_w,max_h = xb-xa-2*config.cell_padding_dots*scale,yb-ya-2*config.cell_padding_dots*scale
        size = target_size*scale
        while True:
            font = ImageFont.truetype(str(font_path),size)
            bounds = draw.textbbox((0,0),text,font=font)
            tw,th = bounds[2]-bounds[0],bounds[3]-bounds[1]
            if (tw <= max_w and th <= max_h) or size <= 8*scale:
                break
            size -= 1
        if tw > max_w or th > max_h:
            raise ValueError("文字过长，无法在最小字号下完整排入标签")
        draw.text(((xa+xb-tw)/2-bounds[0],(ya+yb-th)/2-bounds[1]),text,fill=0,font=font)

    center("名称",(x0,y0,split_x,split_y),config.font_size)
    center(config.name,(split_x,y0,x1,split_y),config.font_size)
    center("编号",(x0,split_y,split_x,y1),config.font_size)
    center(config.label(number),(split_x,split_y,x1,y1),config.number_font_size)
    return image.resize((width,height),Image.Resampling.LANCZOS).point(lambda p:255 if p>=160 else 0).convert("1")


def generate(config: Config, directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    # File names use integers, NOT user supplied label text (avoid path traversal).
    for number in range(config.start,config.end+1):
        make_label(config,number).save(directory/f"label-{number:06}.png",dpi=(203.2,203.2))
    first = make_label(config,config.start)
    first.resize((960,480),Image.Resampling.NEAREST).save(directory/"preview.png")
    return config.end-config.start+1
