#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复测：日历（锚点+本地校验修复后）×2 + 开盘啦（冷启动等待修复后）×1。"""
import json
import os
import subprocess
import time
import urllib.request

H = "/data/data/com.termux/files/home"
SK = os.path.join(H, "bridge/skills/scripts")
BASE = "http://127.0.0.1:8900"

TASKS = [
    ("打开日历看今天有日程吗", "calendar_today", 2),
    ("开盘啦看今日涨停家数", "kaipanla_limit_up", 1),
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


def st_of(sid):
    try:
        d = json.load(open(os.path.join(SK, sid + ".json"), encoding="utf-8"))
        return "status=%s runs=%s ok=%s" % (d.get("status"), d.get("runs"), d.get("ok"))
    except Exception as e:
        return repr(e)


for task, sid, times in TASKS:
    for i in range(times):
        print("\n" + "-" * 66)
        print("[%s] %d/%d：%s" % (sid, i + 1, times, task))
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
            print("  submit -> %s" % rid)
        except Exception as e:
            print("  submit FAILED %r" % (e,))
            continue
        t0, st = time.time(), {}
        while time.time() - t0 < 90:
            time.sleep(3)
            try:
                st = get("/api/status")
            except Exception:
                continue
            if st.get("state") in ("done", "failed", "stopped") and st.get("run_id") == rid:
                break
        print("  state=%s  %.1fs" % (st.get("state"), float(st.get("elapsed") or (time.time() - t0))))
        print("  result=%s" % json.dumps(st.get("result"), ensure_ascii=False)[:200])
        print("  usage=%s" % json.dumps(st.get("usage"), ensure_ascii=False)[:80])
        print("  script -> %s" % st_of(sid))
        time.sleep(1.5)

print("\n最终：")
for _t, sid, _n in TASKS:
    print("  %-20s %s" % (sid, st_of(sid)))
