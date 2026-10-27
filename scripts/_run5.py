#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""5 场景批量测试（含 promote 验证）：
依次跑 5 个 App 的任务；每个脚本跑指定次数；记录 结果/耗时/是否 0 模型，
并读取脚本文件观察 status/runs/ok 的 promote 变化。"""
import json
import os
import subprocess
import sys
import time
import urllib.request

H = "/data/data/com.termux/files/home"
SK = os.path.join(H, "bridge/skills/scripts")
BASE = "http://127.0.0.1:8900"

TASKS = [
    ("开盘啦看今日涨停家数", "kaipanla_limit_up", 1),
    ("今天天气怎么样", "weather_now", 2),
    ("打开日历看今天有日程吗", "calendar_today", 2),
    ("我的闹钟是几点", "clock_alarm", 2),
    ("看下我连的是哪个 WiFi", "settings_wifi", 2),
]


def cenv():
    e = dict(os.environ)
    e.pop("LD_LIBRARY_PATH", None)
    e.pop("LD_PRELOAD", None)
    return e


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=20).read().decode())


def script_state(sid):
    try:
        with open(os.path.join(SK, sid + ".json"), encoding="utf-8") as f:
            d = json.load(f)
        return "status=%s runs=%s ok=%s" % (d.get("status"), d.get("runs"), d.get("ok"))
    except Exception as e:
        return "读取失败 %r" % (e,)


print("场景数 = %d" % len(TASKS))
for task, sid, times in TASKS:
    for i in range(times):
        print("\n" + "-" * 66)
        print("[%s] 第 %d/%d 次：%s" % (sid, i + 1, times, task))
        try:
            st0 = get("/api/status")
            if st0.get("state") == "running":
                post("/api/stop", {})
                time.sleep(3)
        except Exception:
            pass
        subprocess.run(["/system/bin/input", "keyevent", "224"], env=cenv(), timeout=10)
        time.sleep(0.6)
        subprocess.run(["/system/bin/input", "keyevent", "3"], env=cenv(), timeout=10)
        time.sleep(1.2)
        try:
            r = post("/api/run", {"task": task, "mode": "auto"})
            rid = r.get("run_id")
            print("  submit -> %s" % rid)
        except Exception as e:
            print("  submit FAILED: %r" % (e,))
            continue
        t0 = time.time()
        st = {}
        while time.time() - t0 < 75:
            time.sleep(3)
            try:
                st = get("/api/status")
            except Exception:
                continue
            if st.get("state") in ("done", "failed", "stopped") and st.get("run_id") == rid:
                break
        el = st.get("elapsed")
        print("  state=%s  %.1fs" % (st.get("state"), float(el or (time.time() - t0))))
        print("  result=%s" % json.dumps(st.get("result"), ensure_ascii=False)[:180])
        print("  usage=%s" % json.dumps(st.get("usage"), ensure_ascii=False)[:80])
        print("  script -> %s" % script_state(sid))
        time.sleep(1.5)

print("\n" + "=" * 66)
print("最终脚本状态：")
for _t, sid, _n in TASKS:
    print("  %-20s %s" % (sid, script_state(sid)))
