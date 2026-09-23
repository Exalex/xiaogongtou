#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pc_portal.py — 从 PC 经局域网直连手机 portal HTTP 的"备用操作台"（不需要 adb）

用法：
  python3 pc_portal.py open com.termux        打开 App
  python3 pc_portal.py state                  打印当前屏幕（phone_state + 元素清单）
  python3 pc_portal.py tap X Y                点击
  python3 pc_portal.py text "要输入的文本"      输入文本（UTF-8 自动 base64）
  python3 pc_portal.py key 66                 按键（HOME=3 BACK=4 ENTER=66 WAKEUP=224）
  python3 pc_portal.py swipe x1 y1 x2 y2 [ms] 滑动
  python3 pc_portal.py shot out.png           截图保存
"""
import base64
import json
import os
import sys
import urllib.request

H = "http://192.168.3.170:8080"
TOK = os.environ.get("PORTAL_TOKEN", "")  # 本机 portal 的 Bearer token（见项目 README）


def req(path, payload=None, raw=False, timeout=25):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(H + path, data=data, method="POST" if payload is not None else "GET")
    r.add_header("Authorization", "Bearer " + TOK)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
    if raw:
        return body
    try:
        return json.loads(body)
    except Exception:
        return body.decode("utf-8", "replace")


def unwrap(d):
    if isinstance(d, dict):
        v = d.get("result", d)
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v
    return d


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "state"
    if cmd == "open":
        print(req("/app", {"package": sys.argv[2]}))
    elif cmd == "state":
        d = unwrap(req("/state_full", timeout=35))
        ps = d.get("phone_state") or {}
        print("phone_state:", json.dumps(ps, ensure_ascii=False)[:360])
        lines = []

        def visit(n, depth=0):
            if not isinstance(n, dict) or len(lines) > 150:
                return
            t = (n.get("text") or "").strip()
            c = (n.get("contentDescription") or "").strip()
            rid = (n.get("resourceId") or "").split("/")[-1]
            cls = (n.get("className") or "").split(".")[-1]
            b = n.get("boundsInScreen") or {}
            if (t or c or rid) and b:
                cx = (b.get("left", 0) + b.get("right", 0)) // 2
                cy = (b.get("top", 0) + b.get("bottom", 0)) // 2
                lines.append("(%d,%d) %s | %s | %s | %s" % (cx, cy, t[:56], c[:34], rid[:28], cls[:18]))
            for ch in n.get("children") or []:
                visit(ch, depth + 1)

        visit(d.get("a11y_tree") or {})
        print("\n".join(lines))
    elif cmd == "tap":
        print(req("/tap", {"x": int(sys.argv[2]), "y": int(sys.argv[3])}))
    elif cmd == "text":
        print(req("/keyboard/input", {"base64_text": base64.b64encode(sys.argv[2].encode()).decode(), "clear": False}))
    elif cmd == "key":
        print(req("/keyboard/key", {"key_code": int(sys.argv[2])}))
    elif cmd == "swipe":
        print(req("/swipe", {"startX": int(sys.argv[2]), "startY": int(sys.argv[3]),
                             "endX": int(sys.argv[4]), "endY": int(sys.argv[5]),
                             "duration": int(sys.argv[6]) if len(sys.argv) > 6 else 400}))
    elif cmd == "shot":
        b = req("/screenshot", raw=True, timeout=35)
        with open(sys.argv[2], "wb") as f:
            f.write(b)
        print("saved", sys.argv[2], len(b))
    else:
        print("unknown cmd")


if __name__ == "__main__":
    main()
