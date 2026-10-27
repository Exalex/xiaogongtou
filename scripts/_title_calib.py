#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标题"墨迹网格"模板比对的阈值标定 v2（修正标题带 + 干净样本集）。"""
import os

from PIL import Image

SAMPLES = {
    "EXALEX-a": "logs/wechat_test/mobile/wx4e_sent.png",      # exalex 聊天页（左有4徽标，应被X0排除）
    "EXALEX-b": "logs/wechat_test/mobile/wx3_typed.png",      # exalex 打字态
    "EXALEX-c": "logs/wechat_test/agent_route/08_final_sent.png",  # 17:14 成功页
    "微信支付-1": "logs/wechat_test/run_2012/wx2.png",
    "微信支付-2": "logs/wechat_test/user_run_1945/wx2.png",
    "hao群": "logs/wechat_test/send_test/07_chat_hao.png",
    "列表页微信": "logs/wechat_test/run_2012/wx1.png",         # 负样本：列表页标题「微信」
    "公众号-1": "logs/wechat_test/mobile/wx2c_chat.png",      # 负样本另一类
}

GW, GH = 96, 24
Y0, Y1, X0, X1 = 138, 208, 150, 780   # v2：X 两侧排掉徽标/图标


def title_grid(img):
    px = img.load()
    W, H = img.size
    lo = hi = tlo = thi = None
    for y in range(Y0, Y1, 2):
        for x in range(X0, X1, 2):
            r, g, b = px[x, y][:3]
            if r + g + b < 330:
                if lo is None or x < lo:
                    lo = x
                if hi is None or x > hi:
                    hi = x
                if tlo is None or y < tlo:
                    tlo = y
                if thi is None or y > thi:
                    thi = y
    if lo is None or (hi - lo) < 30 or (thi - tlo) < 16:
        return None, None
    lo = max(0, lo - 2); hi = min(W, hi + 3)
    tlo = max(0, tlo - 2); thi = min(H, thi + 3)
    grid = bytearray(GW * GH)
    for gy in range(GH):
        sy = tlo + (thi - tlo) * gy // GH
        for gx in range(GW):
            sx = lo + (hi - lo) * gx // GW
            acc = n = 0
            for dy in range(3):
                yy = min(sy + dy, H - 1)
                for dx in range(3):
                    xx = min(sx + dx, W - 1)
                    r, g, b = px[xx, yy][:3]
                    acc += (r + g + b) // 3
                    n += 1
            grid[gy * GW + gx] = acc // n
    return bytes(grid), (lo, hi, tlo, thi)


def compare(g1, g2):
    diff_sum = 0
    big50 = big90 = 0
    n = len(g1)
    for a, b in zip(g1, g2):
        d = abs(a - b)
        diff_sum += d
        if d > 50:
            big50 += 1
        if d > 90:
            big90 += 1
    return round(diff_sum / float(n), 1), round(big50 / float(n), 3), round(big90 / float(n), 3)


def main():
    grids = {}
    for name, p in SAMPLES.items():
        if not os.path.exists(p):
            print("跳过（不存在）", name, p)
            continue
        img = Image.open(p).convert("RGB")
        g, bbox = title_grid(img)
        w = (bbox[1] - bbox[0]) if bbox else 0
        grids[name] = g
        print("%-10s bbox=%s 标题宽=%dpx 网格=%s" % (name, bbox, w, "OK" if g else "NULL"))

    print("\n--- 两两对比：平均差 / >50格占比 / >90格占比 ---")
    names = list(grids.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if grids[names[i]] and grids[names[j]]:
                m, b50, b90 = compare(grids[names[i]], grids[names[j]])
                print("  %-10s vs %-10s  差=%5.1f  >50占=%5.3f  >90占=%5.3f"
                      % (names[i], names[j], m, b50, b90))


if __name__ == "__main__":
    main()
