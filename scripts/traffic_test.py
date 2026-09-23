#!/data/data/com.termux/files/usr/bin/python3
# traffic_test.py — 流量实验：lan（局域网）/ wan（公网）两类请求，看哪类能挡住系统冻结
import sys
import time
import urllib.request

kind = sys.argv[1] if len(sys.argv) > 1 else "lan"
dur = int(sys.argv[2]) if len(sys.argv) > 2 else 60
t0 = time.time()
i = 0
while time.time() - t0 < dur:
    i += 1
    try:
        if kind == "lan":
            urllib.request.urlopen("http://192.168.3.75:8888/v1/models", timeout=4).read(1024)
        else:
            urllib.request.urlopen("https://api.typesafe.ai/", timeout=4).read(256)
    except Exception:
        pass
    print("beat", i, kind, round(time.time() - t0, 1))
    time.sleep(1.0)
print("done", kind, i)
