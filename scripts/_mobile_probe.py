"""手机侧环境探针（以 root 身份跑）：screencap / input / portal 本地访问速度。
用途：为"手机本地技能脚本"选择最快的截图与点击通道。
"""
import subprocess, time, urllib.request

print("UID:", subprocess.run(["id"], capture_output=True, text=True).stdout.strip())

t0 = time.time()
r = subprocess.run(["screencap"], capture_output=True, timeout=30)
print("SCREENCAP(raw):", r.returncode, len(r.stdout), "bytes", "%.2fs" % (time.time() - t0))
print("  head:", r.stdout[:16].hex())

t0 = time.time()
r2 = subprocess.run(["screencap", "-p"], capture_output=True, timeout=30)
print("SCREENCAP(png):", r2.returncode, len(r2.stdout), "bytes", "%.2fs" % (time.time() - t0))

try:
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request("http://127.0.0.1:8080/version")
    req.add_header("Authorization", "Bearer a17fe4b9-6651-4e03-9165-a93502ffb61d")
    t0 = time.time()
    b = op.open(req, timeout=10).read()
    print("PORTAL local:", "%.2fs" % (time.time() - t0), b[:60])
except Exception as e:
    print("PORTAL ERR:", repr(e)[:100])

try:
    req = urllib.request.Request("http://127.0.0.1:8080/screenshot")
    req.add_header("Authorization", "Bearer a17fe4b9-6651-4e03-9165-a93502ffb61d")
    t0 = time.time()
    b = op.open(req, timeout=30).read()
    print("PORTAL screenshot:", "%.2fs" % (time.time() - t0), len(b), "bytes(base64)")
except Exception as e:
    print("PORTAL SHOT ERR:", repr(e)[:100])
