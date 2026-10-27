#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署后自检：确认确定性骨架模块与账本在手机端可用。"""
import os
import sys

H = "/data/data/com.termux/files/home"
sys.path.insert(0, H)
os.environ.setdefault("HOME", H)

import anchors as A          # noqa: E402
import scripts_lib as S      # noqa: E402

print("HOME =", os.path.expanduser("~"))
print("anchors / scripts_lib 导入 OK")
print("families =", sorted(S.load_families()))
print("scripts  =", [s["id"] for s in S.load_scripts()])
print("guards   =", [g["id"] for g in S.load_guards()])
cards = S.cards_of({})
for pk in ("com.sina.weibo", "com.aiyu.kaipanla", "com.android.settings"):
    c = cards.get(pk) or {}
    print("%-26s pages=%s home=%s spots=%d"
          % (pk, [p["name"] for p in (c.get("pages") or [])],
             bool(c.get("home_path")), len(c.get("spots") or [])))
print("锚点：", A.anchor_level({"text": ["实时热点"]},
                               [(0, 1, 1, "实时热点", False)], "", None))
