#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机端真机测试：唤醒 → 回桌面 → 提交任务 → 轮询状态 → 打印结论。
用法：python3 _run_test.py "任务文本" [mode] [最长等待秒]"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8900"
TASK = sys.argv[1] if len(sys.argv) > 1 else "打开设置，告诉我电池电量百分比"
MODE = sys.argv[2] if len(sys.argv) > 2 else "auto"
WAIT = int(sys.argv[3]) if len(sys.argv) > 3 else 180


def cenv():
    e = dict(os.environ)
    e.pop("LD_LIBRARY_PATH", None)
    e.pop("LD_PRELOAD", None)
    return e


def sh(*args):
    return subprocess.run(["/system/bin/input"] + list(args), env=cenv(),
                          capture_output=True, timeout=15)


def post(path, payload):
    req = urllib.request.Request(BASE + path,
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=20).read().decode())


print("=== 清场：停掉遗留任务 ===")
try:
    st0 = get("/api/status")
    if st0.get("state") == "running":
        print("stop ->", json.dumps(post("/api/stop", {}), ensure_ascii=False)[:120])
        time.sleep(3)
    else:
        print("idle（无遗留任务）")
except Exception as e:
    print("清场检查失败:", repr(e))

print("=== 复位：唤醒 + 回桌面 ===")
sh("keyevent", "224")          # WAKEUP
time.sleep(0.8)
sh("keyevent", "3")            # HOME
time.sleep(1.5)

print("=== 提交任务：%s（mode=%s）===" % (TASK, MODE))
try:
    print("submit ->", json.dumps(post("/api/run", {"task": TASK, "mode": MODE}),
                                  ensure_ascii=False)[:200])
except Exception as e:
    print("submit FAILED:", repr(e))
    sys.exit(1)

t0 = time.time()
last = None
while time.time() - t0 < WAIT:
    time.sleep(3)
    try:
        st = get("/api/status")
    except Exception as e:
        print("status error:", repr(e))
        continue
    cur = (st.get("state"), st.get("step"))
    if cur != last:
        print("[%5.1fs] state=%s step=%s elapsed=%s"
              % (time.time() - t0, st.get("state"), st.get("step"), st.get("elapsed")))
        last = cur
    if st.get("state") in ("done", "failed", "stopped", "idle") and st.get("run_id"):
        if st.get("state") != "running":
            break

print("\n=== 最终状态 ===")
st = get("/api/status")
for k in ("state", "run_id", "task", "mode", "engine", "step", "elapsed",
          "result", "failed_reason", "usage"):
    if k in st:
        print("%-14s %s" % (k, json.dumps(st[k], ensure_ascii=False)[:400]))
