import os
import subprocess
import sys

os.chdir("/data/data/com.termux/files/home")
sys.path.insert(0, "/data/data/com.termux/files/home")

subprocess.run(["/system/bin/am", "force-stop", "com.sina.weibo"])
import time
time.sleep(1)

import mini_agent

print("PATH=", os.environ.get("PATH"))
print("try resolve:")
r = subprocess.run(["cmd", "package", "resolve-activity", "--brief", "com.sina.weibo"],
                   capture_output=True, text=True, timeout=10, env=mini_agent._clean_env())
print("  rc=", r.returncode)
print("  out=", repr(r.stdout))
print("  err=", repr(r.stderr))

res = mini_agent.shadow_open_app("com.sina.weibo", 70)
print("shadow_open_app RESULT:", repr(res))
