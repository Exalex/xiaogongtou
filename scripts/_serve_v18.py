# -*- coding: utf-8 -*-
"""_serve_v18.py — 本机 8899 HTTP 服务（手机浏览器访问）：
   /t          触发页（自动向手机本机 console /api/run 发 pi 任务：恢复 adb tcp）
   /xgt.apk    v1.8 APK 下载（备用安装通道）
   /beacon?... 页面信标 → 记入 serve.log（可观测页面是否执行/触发结果）
日志: logs/v18/serve.log
"""
import os
import time
import socketserver
import http.server
from functools import partial

BASE = r'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/v18'
DIR = os.path.join(BASE, 'serve')
LOG = os.path.join(BASE, 'serve.log')
PORT = 8899

os.makedirs(DIR, exist_ok=True)


def log(line):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), line))


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        msg = fmt % args
        log('%s | %s' % (self.client_address[0], msg))

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


class Srv(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    log('server start on 0.0.0.0:%d dir=%s' % (PORT, DIR))
    with Srv(('0.0.0.0', PORT), partial(H, directory=DIR)) as srv:
        srv.serve_forever()
