#!/usr/bin/env python3
"""量测 screencap 原始 RGBA 帧（可限定区域）：饱和度 / 黑位 / 对比度 / 白点。纯标准库。"""
import sys, struct

def analyze(path, y0=None, y1=None, label=""):
    with open(path, 'rb') as f:
        data = f.read()
    w, h, fmt, _cs = struct.unpack('<IIII', data[:16])
    px = data[16:]
    y0 = 0 if y0 is None else y0
    y1 = h if y1 is None else min(y1, h)

    step = 3
    sat_sum = 0.0
    lum_hist = [0] * 256
    white_bad = 0
    n = 0
    stride = w * 4
    for y in range(y0, y1, step):
        base = y * stride
        for x in range(0, w, step):
            i = base + x * 4
            r, g, b = px[i], px[i + 1], px[i + 2]
            mx = r if r > g else g
            if b > mx:
                mx = b
            mn = r if r < g else g
            if b < mn:
                mn = b
            sat_sum += 0.0 if mx == 0 else (mx - mn) / mx
            lum_hist[(r * 299 + g * 587 + b * 114) // 1000] += 1
            if mx > 235 and (mx - mn) < 12:
                white_bad += 1   # 高亮但几乎无彩 = 死白
            n += 1

    cum = 0
    q = {}
    targets = [0.02, 0.05, 0.10, 0.50, 0.90, 0.95, 0.98]
    ti = 0
    for v in range(256):
        cum += lum_hist[v]
        frac = cum / n
        while ti < len(targets) and frac >= targets[ti]:
            q[targets[ti]] = v
            ti += 1
    print(f"-- {label or path}  region y={y0}..{y1}  samples={n}")
    print(f"   mean_saturation = {sat_sum/n:.4f}")
    print(f"   luma p2={q.get(0.02)} p5={q.get(0.05)} p10={q.get(0.10)} "
          f"p50={q.get(0.50)} p90={q.get(0.90)} p95={q.get(0.95)} p98={q.get(0.98)}")
    print(f"   black_floor(p5) = {q.get(0.05)}   contrast(p95-p5) = "
          f"{(q.get(0.95) or 0) - (q.get(0.05) or 0)}   dead_white% = {100.0*white_bad/n:.2f}")

if __name__ == '__main__':
    args = sys.argv[1:]
    y0 = y1 = None
    files = []
    i = 0
    while i < len(args):
        if args[i] == '--y0': y0 = int(args[i+1]); i += 2
        elif args[i] == '--y1': y1 = int(args[i+1]); i += 2
        else: files.append(args[i]); i += 1
    for p in files:
        analyze(p, y0, y1)
