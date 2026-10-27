# -*- coding: utf-8 -*-
"""_vlm_probe.py — 探测本地 LLM 端点是否支持视觉输入（image_url）。

用法：
  python _vlm_probe.py <图片路径> [模型名]
说明：系统代理 7897 会拦局域网 → 显式绕开（ProxyHandler({})）。
"""
import base64
import json
import os
import sys
import urllib.request

BASE = os.environ.get("LLM_BASE", "http://192.168.3.75:8888/v1")
KEY = os.environ.get("LLM_KEY", "123")
MODEL = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("LLM_MODEL", "qwen3.8-flash-next")
IMG = sys.argv[1]

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

with open(IMG, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = {
    "model": MODEL,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "这张手机截图里，屏幕顶部标题是什么？底部四个标签分别是什么？只回答你真正看到的。"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
        ],
    }],
    "max_tokens": 200,
    "temperature": 0,
}
req = urllib.request.Request(BASE.rstrip("/") + "/chat/completions",
                            data=json.dumps(payload).encode(),
                            method="POST")
req.add_header("Authorization", "Bearer " + KEY)
req.add_header("Content-Type", "application/json")
try:
    with _OPENER.open(req, timeout=90) as r:
        d = json.loads(r.read())
    print("OK model=%s" % d.get("model"))
    print((d["choices"][0]["message"].get("content") or "")[:600])
except Exception as e:
    print("FAIL %r" % (e,))
    try:
        print(getattr(e, "read", lambda: b"")()[:400])
    except Exception:
        pass