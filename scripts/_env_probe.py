#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_env_probe.py — 定位"agent 上下文里 screencap 输出 0 字节"的根因：
对比 (A) 继承环境 / (B) 去掉 LD_LIBRARY_PATH / (C) 干净最小环境 三种情况下 screencap 的结果。
"""
import os
import subprocess

print("LD_LIBRARY_PATH =", os.environ.get("LD_LIBRARY_PATH"))
print("PATH            =", os.environ.get("PATH"))
print("HOME            =", os.environ.get("HOME"))


def probe(tag, env=None):
    try:
        r = subprocess.run(["/system/bin/screencap"], capture_output=True, timeout=30, env=env)
        print("%s rc=%s len=%d err=%r" % (tag, r.returncode, len(r.stdout),
                                          (r.stderr or b"")[:150]))
    except Exception as e:
        print("%s EXC %r" % (tag, e))


probe("A 继承环境    ", None)
env_b = dict(os.environ)
env_b.pop("LD_LIBRARY_PATH", None)
probe("B 去LD_LIBRARY", env_b)
env_c = {"PATH": "/system/bin:/system/xbin", "ANDROID_ROOT": "/system",
         "ANDROID_DATA": "/data", "HOME": "/"}
probe("C 干净最小env ", env_c)
