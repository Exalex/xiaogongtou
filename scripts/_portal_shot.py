# -*- coding: utf-8 -*-
"""_portal_shot.py — portal 截图并解码保存为 PNG。
用法: python _portal_shot.py <out.png>
"""
import sys
import json
import base64
import urllib.request

TOK = 'a17fe4b9-6651-4e03-9165-a93502ffb61d'
out = sys.argv[1] if len(sys.argv) > 1 else '_shot.png'
o = urllib.request.build_opener(urllib.request.ProxyHandler({}))
r = urllib.request.Request('http://192.168.3.170:8080/screenshot')
r.add_header('Authorization', 'Bearer ' + TOK)
raw = o.open(r, timeout=30).read()
try:
    d = json.loads(raw)
    b = base64.b64decode(d.get('result') or d.get('data'))
except Exception:
    b = raw
open(out, 'wb').write(b)
print('saved', out, len(b))
