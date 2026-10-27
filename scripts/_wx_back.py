# -*- coding: utf-8 -*-
"""_wx_back.py — 连按 BACK N 次并截图（把手机从微信子页面退回主界面用）。

用法：python _wx_back.py [次数] [输出png]
"""
import base64
import json
import os
import sys
import time
import urllib.request

TOK = os.environ.get("PORTAL_TOKEN", "a17fe4b9-6651-4e03-9165-a93502ffb61d")
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def req(path, payload=None, raw=False):
    d = json.dumps(payload).encode() if payload else None
    r = urllib.request.Request("http://192.168.3.170:8080" + path, data=d,
                               method="POST" if d else "GET")
    r.add_header("Authorization", "Bearer " + TOK)
    if d:
        r.add_header("Content-Type", "application/json")
    with OP.open(r, timeout=45) as x:
        b = x.read()
    return b if raw else json.loads(b)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    out = sys.argv[2] if len(sys.argv) > 2 else "logs/wechat_test/vision/state_now.png"
    for i in range(n):
        print("BACK", i + 1, req("/keyboard/key", {"key_code": 4}))
        time.sleep(1.4)
    time.sleep(0.6)
    raw = req("/screenshot", raw=True)
    d = json.loads(raw)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(base64.b64decode(d["result"]))
    print("saved", out)


if __name__ == "__main__":
    main()
