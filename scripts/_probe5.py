#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量探测：依次打开 5 个 App，关掉挡路弹窗，打印各自首页元素清单。
用途：为「5 个场景」写脚本 + 标定卡片 pages/spots。"""
import os
import subprocess
import sys
import time

H = "/data/data/com.termux/files/home"
sys.path.insert(0, H)
os.environ["HOME"] = H

import mini_agent as M   # noqa: E402

TARGETS = [
    ("com.aiyu.kaipanla", 10),        # 开盘啦（已有脚本，做对照）
    ("com.android.settings", 7),      # 设置
    ("com.coloros.weather2", 8),      # 天气
    ("com.coloros.calendar", 8),      # 日历
    ("com.coloros.alarmclock", 8),    # 时钟/闹钟
]


def cenv():
    e = dict(os.environ)
    e.pop("LD_LIBRARY_PATH", None)
    e.pop("LD_PRELOAD", None)
    return e


def start(pkg):
    r = subprocess.run(["/system/bin/cmd", "package", "resolve-activity", "--brief", pkg],
                       env=cenv(), capture_output=True, text=True, timeout=15)
    comp = ""
    for ln in reversed((r.stdout or "").strip().splitlines()):
        ln = ln.strip()
        if "/" in ln and " " not in ln:
            comp = ln
            break
    if not comp:
        print("  !! 未解析到入口 Activity（App 可能未安装）")
        return False
    subprocess.run(["/system/bin/am", "start", "-n", comp],
                   env=cenv(), capture_output=True, timeout=25)
    return True


def dump(tag=""):
    p = M.Portal()
    el, cur = M._script_elems(p)
    n = M._dismiss_popups(p, el)
    if n:
        el, cur = M._script_elems(p)
    print("  [%s] 前台=%r activity=%r 元素=%d 页面=%r"
          % (tag, cur, M.get_activity(), len(el), M.page_of(cur, el)))
    for e in el:
        s = str(e[3]).strip()
        if s and e[2] > 100:                      # 跳过状态栏噪声
            print("      (%4d,%4d) %s%s" % (e[1], e[2], s[:58], "  [可点]" if e[4] else ""))
    return el, cur


for pkg, wait in TARGETS:
    print("\n" + "=" * 72)
    print("APP: %s" % pkg)
    print("=" * 72)
    subprocess.run(["/system/bin/input", "keyevent", "3"], env=cenv(), timeout=10)
    time.sleep(1.0)
    if not start(pkg):
        continue
    time.sleep(wait)
    dump("首页")
