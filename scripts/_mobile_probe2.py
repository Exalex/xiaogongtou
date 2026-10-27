"""probe2: 测试 Termux 用户（uid 10353）能否直接调用 su（决定 agent 接入的技能通道）"""
import subprocess

print("whoami:", subprocess.run(["id"], capture_output=True, text=True).stdout.strip()[:100])
try:
    r = subprocess.run(["su", "-c", "id"], capture_output=True, text=True, timeout=15)
    print("su rc:", r.returncode)
    print("su out:", r.stdout.strip()[:100])
    print("su err:", r.stderr.strip()[:100])
except Exception as e:
    print("su ERR:", repr(e)[:150])

try:
    r2 = subprocess.run(["su", "-c", "/system/bin/screencap"], capture_output=True, timeout=30)
    print("su screencap:", r2.returncode, len(r2.stdout), "bytes")
except Exception as e:
    print("su screencap ERR:", repr(e)[:150])
