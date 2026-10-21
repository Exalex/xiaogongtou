#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_task.py — 平板任务跑批脚手架

用法:
  python run_task.py --task "在酷安搜索微信" --reset com.coolapk.market --tag T1

做的事:
  1. force-stop 目标 App（清掉"恢复上次页面"导致的状态漂移）
  2. 回桌面 + 亮屏
  3. POST /api/run 提交任务
  4. 轮询 /api/status 直到结束（超时可配）
  5. 把 status 全文 + trace 存到 runs/<tag>-<rid>.json
  6. 打印一行结论 + 爆点统计

退出码: 0=成功(done), 1=失败, 2=超时
"""
import argparse
import json
import os
import subprocess
import sys
import time

ADB = r"D:\workspace\workbuddySpace\githubResearch\.tools\platform-tools\adb.exe"
OUT = r"D:\workspace\workbuddySpace\githubResearch\mobilerun-ondevice\logs\taskruns"


def sh(cmd, timeout=120):
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        r = subprocess.run([ADB, "shell", cmd], capture_output=True,
                           timeout=timeout, env=env)
        return (r.stdout or b"").decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired:
        # 设备忙时 adb shell 偶发超时：不要让脚手架崩掉，交给上层重试
        return "__ADB_TIMEOUT__"
    except Exception as e:
        return "__ADB_ERR__:%r" % (e,)


def api(path, timeout=20, method="GET", payload=None):
    cmd = "curl -s --max-time %d -X %s http://127.0.0.1:8900%s" % (timeout, method, path)
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).replace("'", "'\"'\"'")
        cmd += " -H 'Content-Type: application/json' -d '%s'" % body
    t = sh(cmd, timeout=timeout + 10)
    try:
        return json.loads(t)
    except Exception:
        return {"_raw": t}


def reset_device(pkg):
    sh("input keyevent KEYCODE_WAKEUP", timeout=30)
    time.sleep(0.5)
    if pkg:
        sh("/debug_ramdisk/su -c 'am force-stop %s'" % pkg, timeout=40)
    sh("input keyevent KEYCODE_HOME", timeout=30)
    time.sleep(2.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--reset", default="", help="要 force-stop 的包名")
    ap.add_argument("--tag", default="T")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--mode", default="auto")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)

    print("[harness] reset: pkg=%s" % (args.reset or "-"), flush=True)
    reset_device(args.reset)

    st = api("/api/status", timeout=10)
    if st.get("state") == "running":
        print("[harness] 上一个任务还在跑，先停", flush=True)
        api("/api/stop", timeout=15, method="POST", payload={})
        time.sleep(2)

    r = api("/api/run", timeout=20, method="POST",
            payload={"task": args.task, "mode": args.mode})
    rid = r.get("run_id")
    if not rid:
        print("[harness] 提交失败: %r" % (r,), flush=True)
        return 2
    print("[harness] run_id=%s task=%s" % (rid, args.task), flush=True)

    t0 = time.time()
    last_step = -1
    while time.time() - t0 < args.timeout:
        time.sleep(6)
        s = api("/api/status", timeout=10)
        state = s.get("state")
        step = s.get("step") or 0
        if step != last_step:
            last_step = step
            print("  [+%3ds] %s step=%s" % (int(time.time() - t0), state, step), flush=True)
        if state != "running":
            break
    else:
        state = "timeout"

    s = api("/api/status", timeout=15)
    path = os.path.join(OUT, "%s-%s.json" % (args.tag, rid))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)

    dur = s.get("elapsed") or (time.time() - t0)
    print("", flush=True)
    print("=" * 70, flush=True)
    print("[结果] state=%s step=%s %.1fs" % (s.get("state"), s.get("step"), dur), flush=True)
    print("[回答] %s" % (s.get("result") or ""), flush=True)
    if s.get("failed_reason"):
        print("[失败] %s" % s.get("failed_reason"), flush=True)
    print("[存档] %s" % path, flush=True)
    print("--- 日志 ---", flush=True)
    for l in s.get("lines") or []:
        print("  " + l, flush=True)

    return 0 if s.get("state") == "done" else (2 if state == "timeout" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
