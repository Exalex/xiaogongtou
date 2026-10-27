#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查手机侧 LLM 通路：局域网 qwen（192.168.3.75:8888）与公网 Jev。"""
import json
import time
import urllib.request

LAN = "http://192.168.3.75:8888/v1/models"
JEV = "https://api.typesafe.ai/v1/systemone"

_op = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(name, url, timeout=8, data=None, headers=None):
    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=data, headers=headers or {})
        r = _op.open(req, timeout=timeout)
        body = r.read()[:120]
        print("%-10s OK   %d  %.1fs  %s" % (name, r.status, time.time() - t0,
                                            body.decode("utf-8", "replace")[:80]))
        return True
    except Exception as e:
        print("%-10s FAIL %.1fs  %r" % (name, time.time() - t0, e))
        return False


print("--- 局域网 qwen ---")
probe("qwen", LAN)

print("--- 公网 Jev ---")
probe("jev", JEV, timeout=10, data=json.dumps({"input": "ping"}).encode(),
      headers={"Content-Type": "application/json", "Authorization": "Bearer x"})

print("--- DNS/网络 ---")
try:
    import socket
    print("dns api.typesafe.ai ->", socket.gethostbyname("api.typesafe.ai"))
except Exception as e:
    print("dns FAIL", repr(e))
