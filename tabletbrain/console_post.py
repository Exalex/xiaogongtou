#!/data/data/com.termux/files/usr/bin/python3
# console_post.py — 从手机本机（Termux）向控制台提交任务（断线实验 / 脚本化入口）
# 用法：python3 console_post.py "任务文本" [auto|jev|qwen]
import json
import sys
import urllib.request

task = sys.argv[1] if len(sys.argv) > 1 else "打开设置，告诉我电池电量百分比"
mode = sys.argv[2] if len(sys.argv) > 2 else "auto"
req = urllib.request.Request(
    "http://127.0.0.1:8900/api/run",
    data=json.dumps({"task": task, "mode": mode}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
print(urllib.request.urlopen(req, timeout=10).read().decode())
