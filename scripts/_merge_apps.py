#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 _seed/apps.json 的新字段（home_path/pages/spots/version）合并进手机现有 apps.json。
用法：python3 _merge_apps.py <手机apps.json> <seed/apps.json> <输出路径>
保留手机侧学到的 hint（纯文本条目），只叠加新结构字段。"""
import json
import sys

phone_p, seed_p, out_p = sys.argv[1], sys.argv[2], sys.argv[3]
phone = json.load(open(phone_p, encoding="utf-8"))
seed = json.load(open(seed_p, encoding="utf-8"))

merged = dict(phone)
for k, v in seed.items():
    old = merged.get(k)
    nv = dict(v)
    nv.pop("hint", None)                 # 不带 hint → 让内置/已学到的 hint 生效
    if isinstance(old, dict):
        m = dict(old)
        m.update(nv)
        merged[k] = m
    else:
        merged[k] = nv
json.dump(merged, open(out_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("merged ->", out_p)
for k in sorted(seed):
    c = merged.get(k) or {}
    print("  %-28s pages=%s home=%s spots=%d"
          % (k, [p.get("name") for p in (c.get("pages") or [])],
             bool(c.get("home_path")), len(c.get("spots") or [])))
