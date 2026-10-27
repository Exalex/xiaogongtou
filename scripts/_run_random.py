#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随机任务验收：从任务池随机抽 N 个任务，逐个跑，以「一次跑通」为标准。
输出每任务：结果 / 耗时 / 步数 / 模型调用(jev,qwen) / 走的通路(脚本|骨架|自由循环)。
用法：python3 _run_random.py [N] [单任务最长等待秒]"""
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8900"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4
WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 130
RUNS = "/data/data/com.termux/files/home/bridge/runs"

# 任务池：只用**低风控**应用 + 我们真正需要的任务类型（读数 / 列表 / 进页面看数据）。
# 2026-10-12 用户口径：不要用风控大的网站/APP（微博/淘宝/抖音/头条等一律不进池）。
POOL = [
    "打开开盘啦，看今天涨停家数",
    "打开开盘啦，看今天跌停家数",
    "打开开盘啦，看今天的连板高度",
    "打开B站，看热门榜前三个视频是什么",
    "打开B站，看我的关注有多少个",
    "打开天气，看今天多少度",
    "打开天气，看明天的天气怎么样",
    "打开时钟，看我的闹钟是几点",
    "打开日历，看今天有什么日程",
    "打开设置，看看现在连的WiFi叫什么",
    "打开设置，告诉我电池电量百分比",
    "打开计算器，算 123 乘 456",
    "打开便签，看第一条笔记是什么",
    "打开指南针，看现在朝向多少度",
]


def cenv():
    e = dict(os.environ)
    e.pop("LD_LIBRARY_PATH", None)
    e.pop("LD_PRELOAD", None)
    return e


def sh(*args):
    try:
        subprocess.run(["/system/bin/input"] + list(args), env=cenv(),
                       capture_output=True, timeout=15)
    except Exception:
        pass


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=20).read().decode())


def run_one(task, idx):
    print("\n" + "=" * 60)
    print("[%d] 任务：%s" % (idx, task))
    print("=" * 60)
    try:
        st0 = get("/api/status")
        if st0.get("state") == "running":
            post("/api/stop", {})
            time.sleep(3)
    except Exception as e:
        print("清场失败:", repr(e))
    sh("keyevent", "224")
    time.sleep(0.8)
    sh("keyevent", "3")
    time.sleep(1.5)
    try:
        post("/api/run", {"task": task, "mode": "auto"})
    except Exception as e:
        print("提交失败:", repr(e))
        return {"task": task, "ok": False, "why": "submit-fail"}
    t0 = time.time()
    rid = ""
    while time.time() - t0 < WAIT:
        time.sleep(3)
        try:
            st = get("/api/status")
        except Exception:
            continue
        rid = st.get("run_id") or rid
        if st.get("state") in ("done", "failed", "stopped") and rid:
            break
    st = get("/api/status")
    res = str(st.get("result") or "")
    state = st.get("state")
    # 从 run 文件里挖通路与模型用量
    path = ""
    try:
        for n in sorted(os.listdir(RUNS), reverse=True):
            if n.endswith(".out"):
                path = os.path.join(RUNS, n)
                break
    except Exception:
        pass
    txt = ""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            txt = f.read()
    except Exception:
        pass
    src = "自由循环"
    if "规划骨架" in txt:
        src = "规划骨架"
    if "命中脚本" in txt:
        src = "已固化脚本"
    usage = ""
    m = re.findall(r"engine-usage: jev=(\d+) qwen=(\d+)", txt)
    if m:
        usage = "jev=%s qwen=%s" % (m[-1][0], m[-1][1])
    nsteps = len(set(re.findall(r"^\[step (\d+)\]", txt, re.M)))   # 按步号去重（一步会打多行）
    # 诚实失败也算"未跑通"：无法/未显示/需登录 都不算成功
    bad = ("无法", "未显示", "需要先登录", "找不到", "没有找到", "失败", "不支持")
    ok = (state == "done") and bool(res) and not any(w in res for w in bad)
    print("→ 结果: %s" % res[:200])
    print("→ 判定: %s | 通路: %s | %s | 步数≈%d | 耗时 %.0fs"
          % ("✅ 跑通" if ok else "❌ 未跑通", src, usage or "-", nsteps, time.time() - t0))
    return {"task": task, "ok": bool(ok), "src": src, "usage": usage,
            "steps": nsteps, "dt": round(time.time() - t0, 1), "res": res[:200]}


def main():
    fixed = os.environ.get("TASKS", "").strip()
    if fixed:
        picked = [t.strip() for t in fixed.split(",") if t.strip()]
    else:
        random.seed()
        picked = random.sample(POOL, min(N, len(POOL)))
    print("本轮随机任务（%d 个）：" % len(picked))
    for i, t in enumerate(picked, 1):
        print("  %d. %s" % (i, t))
    out = []
    for i, t in enumerate(picked, 1):
        try:
            out.append(run_one(t, i))
        except Exception as e:
            out.append({"task": t, "ok": False, "why": repr(e)})
    print("\n" + "=" * 60)
    print("汇总（一次跑通为标准）")
    print("=" * 60)
    n_ok = sum(1 for r in out if r.get("ok"))
    for i, r in enumerate(out, 1):
        print("%d. %s  %s  [%s] %s"
              % (i, "✅" if r.get("ok") else "❌", r.get("task"),
                 r.get("src", "-"), r.get("usage", "")))
    print("\n一次跑通：%d/%d" % (n_ok, len(out)))


if __name__ == "__main__":
    main()
