#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diag_percept.py — 感知通道诊断：对比 portal a11y 树 vs root 桥树

用法: python diag_percept.py
输出: 两个通道的元素清单，以及为什么 portal 少
"""
import json
import os
import subprocess
import sys
import time

ADB = r"D:\workspace\workbuddySpace\githubResearch\.tools\platform-tools\adb.exe"
HOME = "/data/data/com.termux/files/home"


def sh(cmd, timeout=60):
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        r = subprocess.run([ADB, "shell", cmd], capture_output=True, timeout=timeout, env=env)
        return (r.stdout or b"").decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired:
        return "__TIMEOUT__"


def portal_state():
    tok = sh("/debug_ramdisk/su -c 'grep auth_token /data/data/com.mobilerun.portal/shared_prefs/mobilerun_secrets.xml | sed -E \"s/.*>([^<]+)<.*/\\1/\"'", timeout=30).strip()
    raw = sh("curl -s --max-time 15 -H 'Authorization: Bearer %s' http://127.0.0.1:8080/state_full" % tok, timeout=40)
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw[:300]}


def walk(node, out, depth=0):
    if not isinstance(node, dict):
        return
    text = (node.get("text") or "").strip()
    desc = (node.get("contentDescription") or "").strip()
    label = text or desc
    b = node.get("boundsInScreen") or {}
    out.append({
        "d": depth,
        "cls": (node.get("className") or "").split(".")[-1],
        "label": label,
        "click": bool(node.get("isClickable") or node.get("isLongClickable") or node.get("isEditable")),
        "rect": (b.get("left"), b.get("top"), b.get("right"), b.get("bottom")),
        "kids": len(node.get("children") or []),
    })
    for c in node.get("children") or []:
        walk(c, out, depth + 1)


def main():
    print("=" * 72)
    print("通道 A: portal /state_full")
    print("=" * 72)
    d = portal_state()
    r = d.get("result") or {}
    print("phone_state:", json.dumps(r.get("phone_state"), ensure_ascii=False)[:200])
    tr = r.get("a11y_tree") or {}
    nodes = []
    walk(tr, nodes)
    labeled = [n for n in nodes if n["label"]]
    print("总节点 %d / 有标签 %d" % (len(nodes), len(labeled)))
    print("root kids=%s depth_max=%d" % (nodes[0]["kids"] if nodes else "?", max([n["d"] for n in nodes]) if nodes else 0))
    for n in labeled[:40]:
        print("  %s%-20s %-34r %s" % ("  " * n["d"], n["cls"][:20], n["label"][:34], n["rect"]))

    print()
    print("=" * 72)
    print("通道 B: root 桥树 (~/bridge/.tree.json)")
    print("=" * 72)
    seq = "diag%d" % int(time.time())
    sh("/debug_ramdisk/su -c 'printf \"%s tree\" > %s/bridge/.xgt_req'" % (seq, HOME), timeout=30)
    for _ in range(20):
        time.sleep(0.4)
        res = sh("/debug_ramdisk/su -c 'cat %s/bridge/.xgt_res 2>/dev/null'" % HOME, timeout=20)
        if res.strip():
            break
    print("桥返回:", res[:100])
    raw = sh("/debug_ramdisk/su -c 'cat %s/bridge/.tree.json 2>/dev/null'" % HOME, timeout=40)
    if not raw or raw == "__TIMEOUT__":
        print("桥树读取失败")
        return
    try:
        bt = json.loads(raw)
    except Exception as e:
        print("桥树 JSON 解析失败: %r  head=%r" % (e, raw[:200]))
        return
    root = bt.get("tree") if isinstance(bt, dict) and "tree" in bt else bt
    bnodes = []
    walk(root, bnodes)
    blabeled = [n for n in bnodes if n["label"]]
    print("总节点 %d / 有标签 %d" % (len(bnodes), len(blabeled)))
    for n in blabeled[:40]:
        print("  %s%-20s %-34r %s" % ("  " * min(n["d"], 8), n["cls"][:20], n["label"][:34], n["rect"]))

    print()
    print("=" * 72)
    print("差异分析")
    print("=" * 72)
    pa = set(n["label"] for n in labeled)
    pb = set(n["label"] for n in blabeled)
    print("portal 独有: %d" % len(pa - pb))
    print("桥树独有: %d" % len(pb - pa))
    only_b = sorted(pb - pa)[:25]
    if only_b:
        print("桥树独有（portal 漏掉的）:")
        for x in only_b:
            print("   + %r" % x[:50])


if __name__ == "__main__":
    main()
