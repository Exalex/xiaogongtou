# -*- coding: utf-8 -*-
"""_p0_console_test.py — mini_console P0 改动的本地 HTTP 冒烟测试（临时 HOME，端口 8911）。"""
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

TMP = tempfile.mkdtemp(prefix="consoletest_")
os.environ["USERPROFILE"] = TMP
os.environ["HOME"] = TMP
os.environ["CONSOLE_PORT"] = "8911"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mini_console as mc  # noqa: E402

assert mc.xstore is not None, "store.py 未导入"
assert mc.chat_ui is not None, "chat_ui.py 未导入"

srv = mc.Srv(("127.0.0.1", 8911), mc.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def GET(p):
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8911" + p, timeout=5)
        return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def POST(p, obj):
    data = __import__("json").dumps(obj).encode()
    req = urllib.request.Request("http://127.0.0.1:8911" + p, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


st, body = GET("/chat")
assert st == 200 and "对话" in body and "会话历史" in body, (st, body[:120])
print("chat page ok")

st, body = GET("/api/status")
assert st == 200 and '"state"' in body
print("status ok")

st, body = GET("/api/sessions")
assert st == 200 and '"items": []' in body
print("sessions empty ok")

st, body = GET("/api/exec")
assert '"mode": "test"' in body and '"rec": false' in body
print("exec get ok")

st, body = POST("/api/exec", {"rec": True})
assert st == 200 and '"rec": true' in body
st, body = GET("/api/exec")
assert '"rec": true' in body
print("exec set ok")

st, body = GET("/api/session?rid=notfound")
assert st == 404
print("session 404 ok")

st, body = POST("/api/run", {"task": ""})
assert st == 400, (st, body)
print("run empty rejected ok")

st, body = GET("/api/rec?rid=notfound")
assert st == 404
print("rec 404 ok")

# 写一个会话，验证 /api/sessions 与 /api/session
mc.xstore.start_session("test-rid-1", "测试任务：微博热搜", "auto")
mc.xstore.finish_session("test-rid-1", "done", engine="qwen", result="微博热搜前五名分别是：1. 甲；2. 乙；3. 丙；4. 丁；5. 戊。")
st, body = GET("/api/sessions")
assert '"test-rid-1"' in body
st, body = GET("/api/session?rid=test-rid-1")
assert '"rows"' in body and "甲" in body
print("session read ok")

srv.shutdown()
print("ALL OK")
