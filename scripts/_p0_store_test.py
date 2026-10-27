# -*- coding: utf-8 -*-
"""_p0_store_test.py — store.py 的本地回归测试（不碰真机；用临时 HOME）。"""
import json
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="storetest_")
os.environ["USERPROFILE"] = TMP
os.environ["HOME"] = TMP
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import store  # noqa: E402

assert store.DB_PATH.startswith(TMP) or store.DB_PATH.startswith(TMP.replace("\\", "/")), store.DB_PATH

A = "微博热搜前五名分别是：1. 中美达成八点成果共识；2. 张本智和淘汰；3. 中美共同构建建设性战略稳定关系；4. 孙颖莎获胜后仰天长叹；5. 林诗栋vs松岛辉空。"
B = "1. 第一条\n2. 第二条\n3. 第三条"
C = "今天多云，22 到 29 度。"
D = "1、甲；2、乙；3、丙"

items = store.parse_list_items(A)
assert items == ["中美达成八点成果共识", "张本智和淘汰", "中美共同构建建设性战略稳定关系",
                 "孙颖莎获胜后仰天长叹", "林诗栋vs松岛辉空"], items
assert store.parse_list_items(B) == ["第一条", "第二条", "第三条"]
assert store.parse_list_items(C) is None
assert store.parse_list_items(D) == ["甲", "乙", "丙"]
assert store._list_title(A) == "微博热搜前五名分别是", store._list_title(A)
print("parse ok")

store.init()
store.start_session("0927-100000", "微博热搜前五", "auto", exec_mode="test")
store.finish_session("0927-100000", "done", engine="qwen", usage="jev=6 qwen=4",
                     result=A, ended=store.time.time())
d = store.get_session("0927-100000")
assert d and d["session"]["state"] == "done"
assert len(d["messages"]) == 2 and d["messages"][0]["role"] == "user"
assert len(d["datasets"]) == 1 and len(d["datasets"][0]["rows"]) == 5
print("session ok")

store.start_session("0927-101000", "微博热搜前五", "auto")
store.finish_session("0927-101000", "done", result=A)
d2 = store.get_session("0927-101000")
assert len(d2["same_topic"]) == 1 and d2["same_topic"][0]["rid"] == "0927-100000"
print("same_topic ok")

assert len(store.list_sessions(q="微博")) == 2
assert len(store.list_sessions(q="不存在的词")) == 0
print("search ok")

# 回填测试：造两个假 run json
runs = os.path.join(TMP, "bridge", "runs")
os.makedirs(runs, exist_ok=True)
with open(os.path.join(runs, "0926-200536.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "0926-200536", "task": "嗯，去微博找一下热搜前五是什么？", "mode": "auto",
               "started": 1, "ended": 2, "rc": 0, "state": "done",
               "result": A, "engine": "qwen", "usage": "jev=6 qwen=4"}, f)
n = store.import_runs(runs)
assert n == 1, n
assert len(store.list_sessions()) == 3
n = store.import_runs(runs)  # 幂等
assert n == 0
print("import ok")

shutil.rmtree(TMP, ignore_errors=True)
print("ALL OK")
