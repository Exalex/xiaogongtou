#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_scrollprobe.py — 只验证"回列表 + 滑到顶(含关小程序面板) + 定位 exalex"（不点击、不输入、不发送）。
复用 ~/wx_send.py 里的函数（与线上同一份逻辑）。用法（root）：
  python3 /data/local/tmp/_scrollprobe.py
"""
import sys
import time

sys.path.insert(0, "/data/data/com.termux/files/home")
import wx_send as wx   # noqa: E402  （模块级只有函数/常量定义，import 无副作用）

t0 = time.time()
wx.run(["/system/bin/am", "start", "-n", "com.tencent.mm/.ui.LauncherUI"], 20)
time.sleep(0.8)
img = None
tab = 0
for (rx, ry) in ((80, 170), (110, 168), (58, 172), (135, 170)):
    wx.run(["/system/bin/input", "tap", str(rx), str(ry)], 15)
    time.sleep(0.7)
    img = wx.shot()
    tab = wx.bottomtab_green(img)
    print("tap(%d,%d) -> green=%d" % (rx, ry, tab))
    if tab > 40:
        break
if tab <= 40:
    print("!! 没到列表，退出")
    sys.exit(1)

print("== 滑到顶（含关面板）测试 ==")
img = wx.scroll_list_to_top(img)
print("暗比例=%.3f（<0.4 应为正常列表）" % wx.screen_dark_ratio(img))

hit = wx.find_target_row(img, 145, 165)
print("exalex 候选带:", hit)

for rnd in range(2):
    if hit:
        break
    print("未命中 → 上滑翻页（第 %d 次）" % (rnd + 1))
    wx.run(["/system/bin/input", "swipe", "540", "1500", "540", "800", "280"], 12)
    time.sleep(0.9)
    img = wx.shot()
    hit = wx.find_target_row(img, 145, 165)
    print("exalex 候选带:", hit)

print("总耗时 %.1fs" % (time.time() - t0))
