#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""metrics.py —— 任务执行度量与"浪费步数"归因

回答三个问题：
  1. 这轮跑了多少步、多少秒、每步模型多慢
  2. 哪些步是"白烧的"（失败/循环/无变化/被拦截），占多少
  3. 同一个任务的历史趋势（步数/耗时/浪费率有没有变好）

用法:
  python metrics.py --pull                # 从平板拉全部 trace 到本地并分析
  python metrics.py --local              # 只分析本地已拉取的
  python metrics.py --file <trace.jsonl> # 分析单个 trace

输出: 控制台表格 + logs/metrics.json（累积趋势）
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

ADB = r"D:\workspace\workbuddySpace\githubResearch\.tools\platform-tools\adb.exe"
HOME = "/data/data/com.termux/files/home"
LOCAL = r"D:\workspace\workbuddySpace\githubResearch\mobilerun-ondevice\logs\traces"
METRICS = r"D:\workspace\workbuddySpace\githubResearch\mobilerun-ondevice\logs\metrics.json"

# 一条 result/日志文本 → 浪费类别（None 表示有效步）
WASTE_PATTERNS = [
    (r"执行失败", "执行失败"),
    (r"动作循环", "动作循环"),
    (r"重复动作", "重复动作"),
    (r"屏幕无变化", "屏幕无变化"),
    (r"坐标封禁", "坐标封禁"),
    (r"BLOCK", "硬阻断"),
    (r"盲点点击", "盲点点击"),
    (r"索引纠偏", "索引纠偏"),
    (r"感知补盲", "感知补盲(必要成本)"),
    (r"元素过少", "低元素重读(必要成本)"),
    (r"注入 App 锚点", None),          # 正常开销，不算浪费
    (r"权限弹窗", None),
    (r"关闭弹窗", None),
    (r"预期", None),
]


def sh(cmd, timeout=120):
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        r = subprocess.run([ADB, "shell", cmd], capture_output=True, timeout=timeout, env=env)
        return (r.stdout or b"").decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return ""


def pull_all():
    os.makedirs(LOCAL, exist_ok=True)
    # /data/data/com.termux 对 adb shell 用户不可读 → 必须先 root 拷到 /sdcard 再拉
    sh("/debug_ramdisk/su -c 'mkdir -p /sdcard/Download/traces && "
       "cp %s/bridge/runs/*.jsonl /sdcard/Download/traces/ 2>/dev/null; "
       "chmod 644 /sdcard/Download/traces/*.jsonl 2>/dev/null; echo ok'" % HOME, timeout=180)
    listing = sh("ls /sdcard/Download/traces/*.jsonl 2>/dev/null")
    names = [x.strip().split("/")[-1] for x in listing.splitlines() if x.strip().endswith(".jsonl")]
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        subprocess.run([ADB, "pull", "/sdcard/Download/traces/.", LOCAL],
                       capture_output=True, timeout=300, env=env)
    except Exception as e:
        print("[metrics] 拉取失败: %r" % (e,))
    print("[metrics] 平板上有 %d 个 trace，本地 %d 个" % (
        len(names), len(glob.glob(os.path.join(LOCAL, "*.jsonl")))))


def classify(text):
    for pat, cat in WASTE_PATTERNS:
        if re.search(pat, text):
            return cat
    return None


def analyze(path):
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    if not recs:
        return None

    steps = defaultdict(lambda: {"pstart": None, "prompt": None, "reply": None,
                                 "acts": [], "results": []})
    t0 = recs[0].get("ts") or 0
    t_end = recs[-1].get("ts") or t0
    lat = []      # 模型推理耗时（prompt_start → reply）
    action_ms = []  # 动作+感知耗时（reply → 下一步 prompt_start）
    waste = Counter()
    action_kinds = Counter()
    blocked = 0
    for r in recs:
        st = r.get("step")
        if st is None:
            continue
        k = r.get("kind")
        rec = steps[st]
        if k == "prompt_start":
            rec["pstart"] = r.get("ts")
        elif k == "prompt":
            rec["prompt"] = r.get("ts")
        elif k == "reply":
            rec["reply"] = r.get("ts")
            if rec["pstart"]:
                lat.append(round(r["ts"] - rec["pstart"], 2))
            elif rec["prompt"]:
                lat.append(round(r["ts"] - rec["prompt"], 2))
        elif k == "action":
            txt = str(r.get("text") or "")
            rec["acts"].append(txt)
            m = re.search(r'"action"\s*:\s*"([a-z_]+)"', txt)
            action_kinds[m.group(1) if m else "?"] += 1
        elif k == "result":
            txt = str(r.get("text") or "")
            rec["results"].append(txt)
            cat = classify(txt)
            if cat:
                waste[cat] += 1
            if "BLOCK" in txt or "封禁" in txt or "拦截" in txt:
                blocked += 1

    # 动作+感知耗时：上一步 reply 到本步 prompt_start
    _seq = sorted([s for s in steps.keys()])
    for i, s in enumerate(_seq):
        if i == 0:
            continue
        prev = steps[_seq[i - 1]]
        cur = steps[s]
        if prev.get("reply") and cur.get("pstart"):
            d = cur["pstart"] - prev["reply"]
            if 0 <= d < 120:
                action_ms.append(round(d, 2))

    n_steps = max(steps.keys()) if steps else 0
    # 有效步：有 action 且该步的 result 没被判为浪费
    eff, wasted = 0, 0
    for st, rec in steps.items():
        if not rec["acts"]:
            continue
        cats = [classify(t) for t in rec["results"]]
        cats = [c for c in cats if c]
        hard = [c for c in cats if c not in ("感知补盲(必要成本)", "低元素重读(必要成本)",
                                             "索引纠偏")]
        if hard:
            wasted += 1
        else:
            eff += 1

    return {
        "run_id": os.path.basename(path).replace(".trace.jsonl", ""),
        "steps": n_steps,
        "actions": sum(action_kinds.values()),
        "effective": eff,
        "wasted": wasted,
        "waste_rate": round(wasted / max(1, eff + wasted), 3),
        "blocked": blocked,
        "elapsed": round(t_end - t0, 1),
        "llm_calls": len(lat),
        "llm_avg": round(sum(lat) / len(lat), 2) if lat else 0,
        "llm_max": max(lat) if lat else 0,
        "llm_total": round(sum(lat), 1),
        "waste_cats": dict(waste),
        "action_mix": dict(action_kinds),
        "per_step_llm": lat,
        "act_avg": round(sum(action_ms) / len(action_ms), 2) if action_ms else 0,
        "act_total": round(sum(action_ms), 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--file", default="")
    args = ap.parse_args()

    if args.pull:
        pull_all()

    files = [args.file] if args.file else sorted(glob.glob(os.path.join(LOCAL, "*.trace.jsonl")))
    rows = []
    for p in files:
        try:
            m = analyze(p)
            if m:
                rows.append(m)
        except Exception as e:
            print("  分析失败 %s: %r" % (os.path.basename(p), e))

    if not rows:
        print("[metrics] 没有可分析的 trace")
        return

    print()
    print("%-14s %4s %4s %4s %4s %6s %6s %6s %6s %5s" % (
        "run", "步", "有效", "浪费", "阻塞", "总s", "模型s", "动作s", "均步s", "浪费%"))
    print("-" * 84)
    for m in rows:
        print("%-14s %4d %4d %4d %4d %6.0f %6.1f %6.1f %6.2f %4.0f%%" % (
            m["run_id"], m["steps"], m["effective"], m["wasted"], m["blocked"],
            m["elapsed"], m.get("llm_total", 0), m.get("act_total", 0),
            m["llm_avg"], m["waste_rate"] * 100))

    # 汇总
    tot_w = Counter()
    for m in rows:
        for k, v in m["waste_cats"].items():
            tot_w[k] += v
    print()
    print("=== 浪费归因（全部 trace 合计）===")
    for k, v in tot_w.most_common():
        print("  %-22s %3d 次" % (k, v))

    # 单步模型耗时分布
    all_lat = [x for m in rows for x in m["per_step_llm"] if x and x > 0]
    if all_lat:
        all_lat.sort()
        n = len(all_lat)
        print()
        print("=== 单步模型耗时（%d 次调用）===" % n)
        print("  中位 %.1fs / P90 %.1fs / 最大 %.1fs / 合计 %.0fs" % (
            all_lat[n // 2], all_lat[int(n * 0.9)], all_lat[-1], sum(all_lat)))

    os.makedirs(os.path.dirname(METRICS), exist_ok=True)
    old = []
    if os.path.exists(METRICS):
        try:
            old = json.load(open(METRICS, encoding="utf-8"))
        except Exception:
            old = []
    seen = {o.get("run_id") for o in old}
    for m in rows:
        if m["run_id"] not in seen:
            old.append(m)
    json.dump(old, open(METRICS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n[metrics] 趋势已写入 %s（累计 %d 条）" % (METRICS, len(old)))


if __name__ == "__main__":
    main()
