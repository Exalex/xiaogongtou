# -*- coding: utf-8 -*-
"""_tree_stats.py — 解剖 portal /state_full 的原始 a11y 树：节点总数 / 有文本数 / 类名 / 包名。

用途：判断「微信树为空」到底是 ① 根节点为 null（硬屏蔽）还是 ② 节点在、但 text/desc 被清空（混淆）。
用法：python _tree_stats.py <state_full.json> [包名过滤]
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("PORTAL_BASE", "http://192.168.3.170:8080")
TOK = os.environ.get("PORTAL_TOKEN", "")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch():
    r = urllib.request.Request(BASE + "/state_full")
    r.add_header("Authorization", "Bearer " + TOK)
    with _OPENER.open(r, timeout=40) as resp:
        raw = resp.read()
    d = json.loads(raw)
    v = d.get("result", d)
    if isinstance(v, str):
        v = json.loads(v)
    return v


def walk(node, depth, stats, pkg_filter, samples, indent=0):
    if not isinstance(node, dict):
        return
    stats["total"] += 1
    pkg = node.get("packageName") or ""
    cls = (node.get("className") or "").split(".")[-1]
    txt = (node.get("text") or "")
    desc = (node.get("contentDescription") or "")
    rid = (node.get("resourceId") or "").split("/")[-1]
    b = node.get("boundsInScreen") or node.get("bounds") or {}
    has_box = bool(b) and (b.get("right", 0) - b.get("left", 0) > 0)
    if txt or desc:
        stats["labeled"] += 1
    if rid:
        stats["with_id"] += 1
    if node.get("clickable"):
        stats["clickable"] += 1
    if cls:
        stats["classes"][cls] = stats["classes"].get(cls, 0) + 1
    if pkg:
        stats["pkgs"][pkg] = stats["pkgs"].get(pkg, 0) + 1
    if pkg_filter and pkg_filter in pkg and len(samples) < 40:
        samples.append("d%d %s clk=%s box=%s cls=%s id=%s txt=%r desc=%r" % (
            depth, pkg.split(".")[-1], node.get("clickable"), has_box, cls, rid, txt[:40], desc[:40]))
    for ch in node.get("children") or []:
        walk(ch, depth + 1, stats, pkg_filter, samples)


def main():
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        with open(sys.argv[1], encoding="utf-8") as f:
            d = json.load(f)
    else:
        d = fetch()
        with open("logs/wechat_test/state_full_raw_probe.json", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    pkg_filter = sys.argv[2] if len(sys.argv) > 2 else "com.tencent.mm"
    tree = d.get("a11y_tree") or d
    ps = d.get("phone_state") or {}
    print("phone_state:", json.dumps(ps, ensure_ascii=False)[:200])
    stats = {"total": 0, "labeled": 0, "with_id": 0, "clickable": 0, "classes": {}, "pkgs": {}}
    samples = []
    walk(tree, 0, stats, pkg_filter, samples)
    print("nodes=%d 有文本=%d 有id=%d 可点=%d" % (
        stats["total"], stats["labeled"], stats["with_id"], stats["clickable"]))
    print("packages:", dict(sorted(stats["pkgs"].items(), key=lambda kv: -kv[1])[:6]))
    print("classes:", dict(sorted(stats["classes"].items(), key=lambda kv: -kv[1])[:10]))
    print("--- 目标包样本 (%s) ---" % pkg_filter)
    for s in samples:
        print(s)


if __name__ == "__main__":
    main()