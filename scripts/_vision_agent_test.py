# -*- coding: utf-8 -*-
"""_vision_agent_test.py — 在 PC 上干跑 mini_agent 的「视觉兜底」函数（不打手机、只验证代码路径）。

前提：手机 portal 8080 可达（LAN）；PORTAL_TOKEN 环境变量或默认值。
说明：会把 urllib 的代理探测禁掉（本机系统代理 7897 会拦局域网请求）。
"""
import os
import sys
import urllib.request

os.environ.setdefault("PORTAL_BASE", "http://192.168.3.170:8080")
os.environ.setdefault("PORTAL_TOKEN", "a17fe4b9-6651-4e03-9165-a93502ffb61d")
os.environ.setdefault("VISION_FALLBACK", "1")

urllib.request.getproxies = lambda: {}          # 绕系统代理
urllib.request.getproxies_environment = lambda: {}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mini_agent as ma  # noqa: E402

print("VISION_ON =", ma.VISION_ON)
print("vision_apps =", sorted(ma.vision_apps()))

# 1) 先看当前屏幕（应为桌面）
try:
    p = ma.Portal()
    st = p.get_state()
    print("当前应用:", (st.get("phone_state") or {}).get("currentApp"))
except Exception as e:
    print("portal 状态读取失败:", repr(e))

# 2) 干跑视觉兜底
elems = ma.vision_elements("dryrun")
print("视觉元素 %d 个：" % len(elems))
for e in elems[:14]:
    print("  ", e)
