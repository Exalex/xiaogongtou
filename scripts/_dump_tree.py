#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：打印当前前台包名 + 桥树元素清单（用于校准卡片 pages/spots 锚点）。"""
import os
import subprocess
import sys
import time

H = "/data/data/com.termux/files/home"
sys.path.insert(0, H)
os.environ["HOME"] = H

import mini_agent as M   # noqa: E402

pkg = sys.argv[1] if len(sys.argv) > 1 else ""
wait = int(sys.argv[2]) if len(sys.argv) > 2 else 0


def cenv():
    e = dict(os.environ)
    e.pop("LD_LIBRARY_PATH", None)
    e.pop("LD_PRELOAD", None)
    return e


if pkg:
    print("--- 启动 %s ---" % pkg)
    r = subprocess.run(["/system/bin/cmd", "package", "resolve-activity", "--brief", pkg],
                       env=cenv(), capture_output=True, text=True, timeout=15)
    comp = ""
    for ln in reversed((r.stdout or "").strip().splitlines()):
        ln = ln.strip()
        if "/" in ln and " " not in ln:
            comp = ln
            break
    print("activity ->", comp or "(未解析)")
    if comp:
        subprocess.run(["/system/bin/am", "start", "-n", comp],
                       env=cenv(), capture_output=True, timeout=25)
    time.sleep(wait or 6)

p = M.Portal()
el, cur = M._script_elems(p)
n = M._dismiss_popups(p, el)
if n:
    print("--- 关闭了 %d 个弹窗，重新取树 ---" % n)
    el, cur = M._script_elems(p)
print("前台包名(portal) = %r" % cur)
print("activity          = %r" % M.get_activity())
print("元素数            = %d" % len(el))
print("页面身份          = %r" % M.page_of(cur, el))
for e in el[:50]:
    print("   (%4d,%4d) %-46s %s" % (e[1], e[2], repr(str(e[3]))[:46], "可点" if e[4] else ""))
