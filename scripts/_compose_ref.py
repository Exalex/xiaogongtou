# -*- coding: utf-8 -*-
"""拼接 GitHub 参考素材的对比图（边框流光 / 声波线两式）。
输入: logs/_ref/ 下已抽好的 egf_*.png / swf_*.png / slf_*.png
输出: ref_edgelight.png / ref_wave_style.png / ref_line_style.png
"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REF = r'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/_ref'


def get_font(size):
    for p in ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/msyhbd.ttc',
              'C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/arial.ttf']:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


F_TITLE = get_font(25)
F_LABEL = get_font(16)
F_NOTE = get_font(17)

BG = (12, 14, 18)
FG = (234, 238, 244)
FG_DIM = (150, 158, 170)
FG_ACC = (122, 192, 255)


def load_frame(path):
    im = Image.open(path)
    if 'A' in im.getbands():
        rgba = im.convert('RGBA')
        base = Image.new('RGB', rgba.size, (14, 16, 21))
        base.paste(rgba, mask=rgba.split()[-1])
        return base
    return im.convert('RGB')


def edge_metric(path):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.int32)
    H, W, _ = a.shape
    band = max(6, int(H * 0.025))
    e = np.concatenate([
        a[:band, :, :].reshape(-1, 3),
        a[-band:, :, :].reshape(-1, 3),
        a[:, :band, :].reshape(-1, 3),
        a[:, -band:, :].reshape(-1, 3),
    ])
    chroma = float((e.max(axis=1) - e.min(axis=1)).mean())
    bright = float(e.mean())
    return chroma * 2.0 + bright * 0.25


def ink_metric(path):
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.int32)
    corner = a[2, 2].mean()
    g = a.mean(axis=2)
    if corner > 128:
        return float((g < 170).mean()) * 100.0
    return float((g > 90).mean()) * 100.0


def spread_metric(path):
    """抖线式：统计“有墨水的行数”——行数越多说明线条上下抖得越开"""
    a = np.asarray(Image.open(path).convert('RGB')).astype(np.int32)
    g = a.mean(axis=2)
    rows = (g > 90).sum(axis=1) > 3
    return float(rows.sum())


def pick_spread(items, target):
    ms = [it[1] for it in items]
    mx = max(ms) if ms else 0.0
    qual = [it for it in items if it[1] >= 0.45 * mx and it[1] > 0.0]
    if len(qual) < target:
        qual = sorted(items, key=lambda x: -x[1])[:target]
        qual = sorted(qual, key=lambda x: x[0])
    if len(qual) <= target:
        return qual
    idxs = np.linspace(0, len(qual) - 1, target).round().astype(int)
    seen = []
    for i in idxs:
        if int(i) not in seen:
            seen.append(int(i))
    return [qual[i] for i in seen]


def scan(prefix, step, metric):
    files = sorted([f for f in os.listdir(REF) if f.startswith(prefix) and f.endswith('.png')],
                   key=lambda f: int(f[len(prefix):-4]))
    out = []
    for f in files:
        n = int(f[len(prefix):-4])
        src = (n - 1) * step
        out.append((src, metric(os.path.join(REF, f)), os.path.join(REF, f)))
    return out


pad = 16
D = None


def txt_w(d, s, font):
    return d.textlength(s, font=font)


# ============ 1) 边框流光 ============
items = scan('egf_', 3, edge_metric)
chosen = pick_spread(items, 6)
print('edge chosen:', [(c[0], round(c[1], 1)) for c in chosen])

H_T = 440
frames = []
for src, m, p in chosen:
    im = load_frame(p)
    w = int(round(im.width * H_T / im.height))
    frames.append((src, im.resize((w, H_T), Image.LANCZOS), src / 15.0))

title_h, label_h, note_h = 56, 32, 42

# 细节放大面板：从 2.8s 帧裁左下角 → 放大展示光的“层次”
zim = load_frame(chosen[3][2])
zcrop = zim.crop((0, zim.height - 140, 120, zim.height))
ZW = int(round(zcrop.width * H_T / zcrop.height))
zpanel = zcrop.resize((ZW, H_T), Image.LANCZOS)

total_w = pad + sum(fr[1].width + pad for fr in frames) + ZW + pad
total_h = title_h + H_T + label_h + note_h + 8
canvas = Image.new('RGB', (total_w, total_h), BG)
d = ImageDraw.Draw(canvas)
d.text((pad + 2, 14), 'GitHub 参考 ①｜Siri / Gemini 式·屏幕边缘流光（react-native-edge-glow）',
       font=F_TITLE, fill=FG)
x = pad
for src, im, t in frames:
    canvas.paste(im, (x, title_h))
    lt = '%.1fs' % t
    d.text((x + im.width / 2 - txt_w(d, lt, F_LABEL) / 2, title_h + H_T + 6), lt, font=F_LABEL, fill=FG_DIM)
    x += im.width + pad
canvas.paste(zpanel, (x, title_h))
zlt = '细节放大·左下角（×3.7）'
d.text((x + ZW / 2 - txt_w(d, zlt, F_LABEL) / 2, title_h + H_T + 6), zlt, font=F_LABEL, fill=FG_DIM)
d.text((pad + 2, total_h - note_h + 6),
       '光贴住屏幕物理边缘“流动”：颜色沿整圈渐变扫过、非常通透（越靠边越亮越细，向内只薄薄一层气）',
       font=F_NOTE, fill=FG_ACC)
canvas.save(os.path.join(REF, 'ref_edgelight.png'))
print('edge montage ok', canvas.size)

# ============ 2) 声波线·波浪式（2x3） ============
items = scan('swf_', 25, ink_metric)
chosen = pick_spread(items, 6)
print('wave chosen:', [(c[0], round(c[1], 2)) for c in chosen])

FW = 700
frames = []
for src, m, p in chosen:
    im = load_frame(p)
    h = int(round(im.height * FW / im.width))
    frames.append((src, im.resize((FW, h), Image.LANCZOS), src / 60.46))

cell_h = 184 + 28
rows = (len(frames) + 1) // 2
total_w = pad + 2 * FW + 14 + pad
total_h = 56 + rows * cell_h + 46
canvas = Image.new('RGB', (total_w, total_h), BG)
d = ImageDraw.Draw(canvas)
d.text((pad + 2, 14), 'GitHub 参考 ②｜声波线·波浪式（BambooAppsDevTeam/speechwavesanimation）',
       font=F_TITLE, fill=FG)
for i, (src, im, t) in enumerate(frames):
    r, c = i // 2, i % 2
    x = pad + c * (FW + 14)
    y = 56 + r * cell_h
    canvas.paste(im, (x, y))
    lt = '%.1fs' % t
    d.text((x + FW / 2 - txt_w(d, lt, F_LABEL) / 2, y + im.height + 4), lt, font=F_LABEL, fill=FG_DIM)
d.text((pad + 2, total_h - 36),
       '一条平滑波形线：从平线上“鼓”出波峰、随说话起伏流动 —— 你说话它就活，停下它归为平线',
       font=F_NOTE, fill=FG_ACC)
canvas.save(os.path.join(REF, 'ref_wave_style.png'))
print('wave montage ok', canvas.size)

# ============ 3) 声波线·抖线式（纵向） ============
items = scan('slf_', 12, spread_metric)
chosen = pick_spread(items, 4)
print('line chosen:', [(c[0], round(c[1], 2)) for c in chosen])

frames = []
for src, m, p in chosen:
    im = load_frame(p)
    h = int(round(im.height * FW / im.width))
    frames.append((src, im.resize((FW, h), Image.LANCZOS), src / 61.47))

total_w = pad + FW + 76
total_h = 56 + sum(f[1].height + 26 for f in frames) + 46
canvas = Image.new('RGB', (total_w, total_h), BG)
d = ImageDraw.Draw(canvas)
d.text((pad + 2, 14), 'GitHub 参考 ③｜声纹条式（同库 SpeechLineView）', font=F_TITLE, fill=FG)
y = 56
for src, im, t in frames:
    canvas.paste(im, (pad, y))
    lt = '%.1fs' % t
    d.text((pad + FW + 10, y + im.height / 2 - 9), lt, font=F_LABEL, fill=FG_DIM)
    y += im.height + 26
d.text((pad + 2, total_h - 36),
       '同一作者的另一种风格：分段“声纹条”——光段随声音伸缩、游走；节奏感强，但不是“波浪”形态',
       font=F_NOTE, fill=FG_ACC)
canvas.save(os.path.join(REF, 'ref_line_style.png'))
print('line montage ok', canvas.size)
print('ALL DONE')
