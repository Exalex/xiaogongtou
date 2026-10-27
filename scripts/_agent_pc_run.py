# -*- coding: utf-8 -*-
"""_agent_pc_run.py — 在 PC 上跑 mini_agent（adb 不可用时的"远程干跑"：portal 8080 + LAN 模型端点）。

原理：主屏模式（DISPLAY=0）下 agent 的动作全部走 portal HTTP（/tap /swipe /keyboard /app），
      模型走 LAN；所以整个循环可以跑在 PC 上，手机只需开着 portal。
      （只对局域网地址直连、外网照常走系统代理。）

用法：
  python _agent_pc_run.py "任务文本" [--engine qwen] [--max-steps 8]
"""
import os
import sys
import urllib.request

os.environ.setdefault("PORTAL_BASE", "http://192.168.3.170:8080")
os.environ.setdefault("PORTAL_TOKEN", "a17fe4b9-6651-4e03-9165-a93502ffb61d")
os.environ.setdefault("LLM_BASE", "http://192.168.3.75:8888/v1")
os.environ.setdefault("LLM_KEY", "123")

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_ORIG = urllib.request.urlopen


def _smart_urlopen(url, data=None, timeout=None, **kw):
    u = url if isinstance(url, str) else getattr(url, "full_url", "")
    if any(h in u for h in ("192.168.", "127.0.0.1", "localhost")):
        req = url if not isinstance(url, str) else urllib.request.Request(url)
        if data is not None and not isinstance(url, str):
            req.data = data
        return _DIRECT.open(req, timeout=timeout)
    return _ORIG(url, data=data, timeout=timeout, **kw)


urllib.request.urlopen = _smart_urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mini_agent  # noqa: E402

sys.argv = ["mini_agent.py"] + sys.argv[1:]
sys.exit(mini_agent.main())
