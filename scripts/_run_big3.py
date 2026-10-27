#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大型 App 复杂场景测试（模型 + 骨架，mode=auto）：
  1) 今日头条 · 热榜前三条
  2) 抖音 · 搜索「美食」看前三个视频
  3) B站 · 热门榜前三个视频
记录：状态 / 耗时 / 结果 / 模型用量；并打印 agent 日志里的骨架信号（家族/预算/归位/子目标/闸门）。"""
import json
import os
import subprocess
import time
import urllib.request

H = "/data/data/com.termux/files/home"
RUNS = os.path.join(H, "bridge/runs")
BASE = "http://127.0.0.1:8900"

TASKS = [
    "打开今日头条，看热榜前三条是什么",
]


def cenv():
    e = dict(os.environ)
    e.pop("LD_LIBRARY_PATH", None)
    e.pop("LD_PRELOAD", None)
    return e


def post(p, d):
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=20).read().decode())


def get(p):
    return json.loads(urllib.request.urlopen(BASE + p, timeout=20).read().decode())


for task in TASKS:
    print("\n" + "=" * 70)
    print("任务：%s" % task)
    print("=" * 70)
    try:
        if get("/api/status").get("state") == "running":
            post("/api/stop", {})
            time.sleep(3)
    except Exception:
        pass
    subprocess.run(["/system/bin/input", "keyevent", "224"], env=cenv(), timeout=10)
    time.sleep(0.6)
    subprocess.run(["/system/bin/input", "keyevent", "3"], env=cenv(), timeout=10)
    time.sleep(1.2)
    try:
        rid = post("/api/run", {"task": task, "mode": "auto"}).get("run_id")
        print("submit -> %s" % rid)
    except Exception as e:
        print("submit FAILED %r" % (e,))
        continue
    t0, st = time.time(), {}
    while time.time() - t0 < 200:
        time.sleep(4)
        try:
            st = get("/api/status")
        except Exception:
            continue
        if st.get("state") in ("done", "failed", "stopped") and st.get("run_id") == rid:
            break
    print("state=%s  %.1fs  usage=%s"
          % (st.get("state"), float(st.get("elapsed") or (time.time() - t0)),
             json.dumps(st.get("usage"), ensure_ascii=False)))
    print("result=%s" % json.dumps(st.get("result"), ensure_ascii=False)[:300])
    # 骨架信号
    try:
        with open(os.path.join(RUNS, rid + ".out"), encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        sig = [ln.rstrip() for ln in lines
               if any(k in ln for k in ("任务家族", "预算", "起点归位", "归位", "子目标", "闸门",
                                        "命中脚本", "脚本断裂", "页面身份", "经验坐标", "GUARD",
                                        "卡点", "signals", "DONE", "FAILED", "BLOCK"))]
        print("--- 骨架信号（最多 22 行）---")
        for ln in sig[:22]:
            print("  " + ln)
        print("--- 共 %d 步 ---" % sum(1 for ln in lines if ln.startswith("[step ")))
    except Exception as e:
        print("读日志失败 %r" % (e,))
    time.sleep(2)
