# -*- coding: utf-8 -*-
"""生成入口 APK「小工头」的图标资源：
- 主图标（深色圆角方 + 白色「工」字 + 右下绿点）→ entry/res/mipmap-*/ic_launcher.png
- 通知小图标（白色「工」字剪影）→ entry/res/drawable-nodpi/ic_stat_work.png
用法: python gen_entry_icon.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
RES = os.path.join(PROJ, "entry", "res")
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

MAIN = [("mipmap-mdpi", 48), ("mipmap-hdpi", 72), ("mipmap-xhdpi", 96),
        ("mipmap-xxhdpi", 144), ("mipmap-xxxhdpi", 192)]

DARK = (44, 44, 42, 255)
GREEN = (29, 158, 117, 255)
WHITE = (255, 255, 255, 255)


def font_at(px):
    for idx in (0, 1):
        try:
            return ImageFont.truetype(FONT_BOLD, px, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_centered(d, text, font, fill, cx, cy):
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = cx - tw / 2.0 - bbox[0]
    y = cy - th / 2.0 - bbox[1]
    d.text((x, y), text, font=font, fill=fill)


def make_main(size):
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.23), fill=DARK)
    f = font_at(int(s * 0.54))
    draw_centered(d, "工", f, WHITE, s * 0.5, s * 0.475)
    r = int(s * 0.085)
    cx, cy = int(s * 0.78), int(s * 0.78)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN,
              outline=DARK, width=max(2, int(s * 0.014)))
    return img.resize((size, size), Image.LANCZOS)


def make_stat(size=48):
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font_at(int(s * 0.82))
    draw_centered(d, "工", f, WHITE, s * 0.5, s * 0.5)
    return img.resize((size, size), Image.LANCZOS)


def main():
    for dname, px in MAIN:
        out_dir = os.path.join(RES, dname)
        os.makedirs(out_dir, exist_ok=True)
        make_main(px).save(os.path.join(out_dir, "ic_launcher.png"))
        print("ok", dname, "%dpx" % px)
    nd = os.path.join(RES, "drawable-nodpi")
    os.makedirs(nd, exist_ok=True)
    make_stat(48).save(os.path.join(nd, "ic_stat_work.png"))
    print("ok drawable-nodpi/ic_stat_work.png")


if __name__ == "__main__":
    main()
