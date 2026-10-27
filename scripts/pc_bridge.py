#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pc_bridge.py — 从 PC 操作手机 root 桥（xgt-bridge.sh 的文件协议）

用途：portal HTTP 掉线/未启动时的 PC 侧操作台；也是手动回归测试工具。
协议：写 ~/bridge/.xgt_req（"<seq> <op> [args]"）→ 桥执行 → 写 ~/bridge/.xgt_res（"ok"/"err:..."）

用法（需要 adb 连接；可用环境变量 ADB / ANDROID_SERIAL 覆盖）：
  python3 pc_bridge.py tree [out.json]        取完整 a11y 树（默认 ./tree.json）
  python3 pc_bridge.py tap X Y                点击（root input tap）
  python3 pc_bridge.py swipe x1 y1 x2 y2 [ms]
  python3 pc_bridge.py key <keycode>          按键（HOME=3 BACK=4 ENTER=66）
  python3 pc_bridge.py open <package>         打开 App（monkey）
  python3 pc_bridge.py shot out.png           截图（adb exec-out screencap）
  python3 pc_bridge.py raw "<op> [args]"      直接发桥命令，打印响应

桥树格式：{seq, ts, elems:[[idx, x, y, label, clickable, displayId], ...]}
"""
import json
import os
import subprocess
import sys
import time

ADB = os.environ.get("ADB", r"D:\workspace\workbuddySpace\githubResearch\.tools\platform-tools\adb.exe")
SER = os.environ.get("ANDROID_SERIAL", "192.168.3.170:5555")
T = "/data/data/com.termux/files/home/bridge"
REQ = T + "/.xgt_req"
RES = T + "/.xgt_res"
TREE = T + "/.tree.json"


def _adb(args, timeout=30, binary=False):
    r = subprocess.run([ADB, "-s", SER] + args, capture_output=True, timeout=timeout)
    if binary:
        return r.stdout
    return r.stdout.decode("utf-8", "replace").strip()


def _su(cmd, timeout=15):
    """在手机上以 root 执行一条 shell 命令（命令作为单字符串传入，交由设备 shell 解析）。"""
    return _adb(["shell", "su -c '%s'" % cmd], timeout=timeout)


def _seq():
    return "p%d" % (int(time.time() * 1000) % 10_000_000)


def bridge_send(op_line, timeout=12.0):
    """发桥命令并等响应。返回 "ok" / "err:..." / "err: bridge timeout"。"""
    seq = _seq()
    _su("rm -f %s" % RES)
    _su("echo %s %s > %s" % (seq, op_line, REQ))
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.25)
        res = _su("cat %s 2>/dev/null" % RES)
        if res:
            return res
    return "err: bridge timeout"


def bridge_tree(out_path, timeout=15.0):
    """取完整 a11y 树：返回 (ok, 元素数或错误信息)。"""
    seq = _seq()
    _su("rm -f %s %s" % (RES, TREE))
    _su("echo %s tree > %s" % (seq, REQ))
    t0 = time.time()
    res = ""
    while time.time() - t0 < timeout:
        time.sleep(0.25)
        res = _su("cat %s 2>/dev/null" % RES)
        if res:
            break
    if not res.startswith("ok"):
        return False, "bridge: %s" % (res or "timeout")
    raw = _adb(["exec-out", "su -c 'cat %s'" % TREE], timeout=25, binary=True)
    try:
        d = json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        return False, "tree parse: %r (%d bytes)" % (e, len(raw))
    if d.get("seq") != seq:
        return False, "tree seq mismatch: want %s got %s" % (seq, d.get("seq"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    return True, len(d.get("elems") or [])


def show_tree(path, max_lines=120):
    """打印树（按 displayId 分组，可点优先）。"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    elems = d.get("elems") or []
    dpy = {}
    for e in elems:
        try:
            d6 = int(e[5]) if len(e) > 5 else 0
        except Exception:
            d6 = 0
        dpy.setdefault(d6, []).append(e)
    for d6 in sorted(dpy):
        els = dpy[d6]
        print("--- display %d (%d elems) ---" % (d6, len(els)))
        for e in els[:max_lines]:
            try:
                i, x, y, lb, ck = int(e[0]), int(e[1]), int(e[2]), str(e[3]), bool(e[4])
            except Exception:
                continue
            print("(%4d,%5d) %-3s %s" % (x, y, ("T" if ck else " "), lb[:72]))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tree"
    if cmd == "tree":
        out = sys.argv[2] if len(sys.argv) > 2 else "tree.json"
        ok, info = bridge_tree(out)
        print(("ok, %s elems -> %s" % (info, out)) if ok else ("FAIL: %s" % info))
        sys.exit(0 if ok else 1)
    elif cmd == "show":
        show_tree(sys.argv[2])
    elif cmd == "tap":
        print(bridge_send("tap %d %d" % (int(sys.argv[2]), int(sys.argv[3]))))
    elif cmd == "swipe":
        ms = int(sys.argv[6]) if len(sys.argv) > 6 else 500
        print(bridge_send("swipe %d %d %d %d %d" % (
            int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), ms)))
    elif cmd == "key":
        print(bridge_send("key %d" % int(sys.argv[2])))
    elif cmd == "open":
        print(bridge_send("open %s" % sys.argv[2], timeout=20))
    elif cmd == "shot":
        out = sys.argv[2]
        data = _adb(["exec-out", "screencap -p"], timeout=30, binary=True)
        with open(out, "wb") as f:
            f.write(data)
        print("saved %s (%d bytes)" % (out, len(data)))
    elif cmd == "raw":
        print(bridge_send(sys.argv[2]))
    else:
        print("unknown cmd: %s" % cmd)
        sys.exit(2)


if __name__ == "__main__":
    main()
