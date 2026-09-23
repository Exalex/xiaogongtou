#!/usr/bin/env python3
import json
import urllib.request

try:
    r = urllib.request.urlopen("http://192.168.3.75:8888/v1/models", timeout=8)
    d = json.loads(r.read())
    ids = [m.get("id") for m in d.get("data", [])]
    print("LLM OK, models:", ids[:5])
except Exception as e:
    print("LLM FAIL:", repr(e))
