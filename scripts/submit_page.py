#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""submit_page.py —— 从 PC 给平板控制台"隔空"提交任务（不需要 adb）

背景（2026-10-22）：平板无线调试掉了，控制台只绑 127.0.0.1:8900，PC 进不去。
但平板的 Chrome 能访问本机 127.0.0.1 —— 于是让 PC 提供一个页面，
平板打开它，页面 JS 用 no-cors fetch 直接 POST 到本机控制台。

用法：
  python submit_page.py --task "要执行的任务" [--port 8877] [--mode auto]
  → 打印一个 URL，在平板 Chrome 打开即可
"""
import argparse
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>提交任务</title><style>
body{{font:16px/1.6 system-ui,-apple-system,"PingFang SC",sans-serif;
background:#0f1115;color:#e6e8eb;margin:0;padding:32px}}
.box{{max-width:760px;margin:0 auto;background:#171a21;border:1px solid #2a2f3a;
border-radius:14px;padding:24px}}
h1{{font-size:20px;margin:0 0 6px}}
.task{{background:#0b0d11;border:1px solid #2a2f3a;border-radius:10px;
padding:14px;font-size:17px;color:#8ab4ff;word-break:break-all}}
.st{{margin-top:16px;font-size:15px;color:#9aa4b2}}
.ok{{color:#4ade80}} .err{{color:#f87171}}
</style></head><body><div class="box">
<h1>正在把任务交给平板</h1>
<div class="task" id="t"></div>
<div class="st" id="s">准备中…</div>
</div>
<script>
const TASK = {task_json};
const MODE = {mode_json};
const s = document.getElementById('s');
document.getElementById('t').textContent = TASK;
(async () => {{
  s.textContent = '提交中…';
  try {{
    await fetch('http://127.0.0.1:8900/api/run', {{
      method: 'POST',
      mode: 'no-cors',
      headers: {{'Content-Type': 'text/plain;charset=UTF-8'}},
      body: JSON.stringify({{task: TASK, mode: MODE, replace: true}})
    }});
    s.className = 'st ok';
    s.textContent = '已提交！3 秒后跳到控制台查看进度…';
  }} catch (e) {{
    s.className = 'st err';
    s.textContent = '提交失败：' + e;
  }}
  setTimeout(() => {{ location.href = 'http://127.0.0.1:8900'; }}, 3000);
}})();
</script></body></html>
"""


def make_handler(task, mode):
    page = PAGE.format(task_json=json.dumps(task, ensure_ascii=False),
                       mode_json=json.dumps(mode, ensure_ascii=False)).encode("utf-8")

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):
            pass

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--mode", default="auto")
    ap.add_argument("--port", type=int, default=8877)
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(args.task, args.mode))
    ips = []
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    print("[submit_page] 监听 0.0.0.0:%d" % args.port, flush=True)
    for ip in ips:
        print("[submit_page] 在平板 Chrome 打开: http://%s:%d/" % (ip, args.port), flush=True)
    print("[submit_page] 任务: %s" % args.task, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
