#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定向探测：设置 / 日历 / 时钟（修正弹窗逻辑后重探）。"""
import os
import subprocess
import sys
import time

H = "/data/data/com.termux/files/home"
sys.path.insert(0, H)
os.environ["HOME"] = H
import mini_agent as M   # noqa: E402

TARGETS = [
    ("com.android.settings", 9),
    ("com.coloros.calendar", 9),
    ("com.coloros.alarmclock", 9),
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
        print("  !! 未解析到入口 Activity")
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
    print("  [%s] 前台=%r 元素=%d 页面=%r" % (tag, cur, len(el), M.page_of(cur, el)))
    for e in el:
        s = str(e[3]).strip()
        if s and e[2] > 100:
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
