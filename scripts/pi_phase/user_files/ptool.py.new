#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ptool — 手机操作工具包（pi / agent 共用；纯标准库，手机本机运行）

子命令:
  state                      前台应用 + 屏幕元素清单（portal /state_full）
  tap X Y                    点按
  swipe X1 Y1 X2 Y2 [ms]     滑动（默认 500ms）
  text "内容"                输入文字（portal 键盘 = 真输入法链路）
  key NAME                   按键（BACK/HOME/ENTER/... 或数字码）
  open <包名|名称>            打开应用（自动解析包名）
  shot [路径]                截图（默认 ~/pi-work/out/shot-<ts>.png）
  battery                    电量/充电状态
  apps                       已安装应用（label + 包名）
  front                      当前前台窗口（dumpsys 全量行）
  wx-send --to 名 --text 内容 微信发送（调 wx_send.py 安全链）

环境变量:
  XGT_DISPLAY=N   影子屏（正式模式）display N；默认 0=主屏。
                  影子模式下：tap/swipe/key 自动带 -d N；open 走 am start --display N；
                  state 走 root 桥树（不读 portal，避免焦点漂移）。
  PORTAL_BASE     portal 地址（默认 http://127.0.0.1:8080）
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

HOME_DIR = os.environ.get("HOME") or "/data/data/com.termux/files/home"
if HOME_DIR in ("/", "/root", "/data"):
    HOME_DIR = "/data/data/com.termux/files/home"
PREFIX = "/data/data/com.termux/files/usr"
PORTAL = os.environ.get("PORTAL_BASE", "http://127.0.0.1:8080")
DISPLAY = str(os.environ.get("XGT_DISPLAY", "0") or "0")
WORK_OUT = os.path.join(HOME_DIR, "pi-work", "out")

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _clean_env():
    """剥掉 Termux 的 LD_LIBRARY_PATH/LD_PRELOAD（否则系统二进制会 CANNOT LINK）。"""
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


def run(cmd, t=20):
    return subprocess.run(cmd, capture_output=True, timeout=t, env=_clean_env())


def _token():
    try:
        with open(os.path.join(HOME_DIR, "bridge", "secrets.json"), encoding="utf-8") as f:
            d = json.load(f)
        return str(d.get("portal_token", ""))
    except Exception:
        return ""


def _unwrap(d):
    if isinstance(d, dict):
        if d.get("status") == "error":
            raise RuntimeError("portal error: %s" % (d.get("message") or d))
        for k in ("result", "data"):
            if k in d:
                v = d[k]
                if isinstance(v, str):
                    try:
                        return json.loads(v)
                    except Exception:
                        return v
                return v
    return d


def portal(path, payload=None, timeout=25):
    url = PORTAL + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET")
    req.add_header("Authorization", "Bearer " + _token())
    if data:
        req.add_header("Content-Type", "application/json")
    with _OPENER.open(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _dprefix():
    return ["-d", DISPLAY] if DISPLAY and DISPLAY != "0" else []


def bridge_cmd(cmd, timeout=8.0):
    """经 root 桥（xgt-bridge.sh）执行命令（与 mini_agent 同协议，影子屏感知用）。"""
    req = os.path.join(HOME_DIR, "bridge/.xgt_req")
    res = os.path.join(HOME_DIR, "bridge/.xgt_res")
    seq = "p%d" % int(time.time() * 1000)
    try:
        try:
            os.remove(res)
        except OSError:
            pass
        with open(req, "w", encoding="utf-8") as f:
            f.write("%s %s" % (seq, cmd))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                with open(res, encoding="utf-8") as f:
                    return (f.read() or "").strip()
            except OSError:
                time.sleep(0.05)
        return "err: bridge timeout"
    except Exception as e:
        return "err: %r" % (e,)


def bridge_elems(dpy, timeout=8.0):
    """桥树取元素（元素第 6 位 = displayId；dpy>0 时过滤该屏）。返回 (elems, err)。"""
    out = os.path.join(HOME_DIR, "bridge/.tree.json")
    try:
        try:
            os.remove(out)
        except OSError:
            pass
        r = bridge_cmd("tree", timeout=timeout)
        if not r.startswith("ok"):
            return None, "bridge: %s" % r
        with open(out, encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        raw = []
        has_dpy = any(len(e) > 5 for e in (d.get("elems") or []))
        for e in d.get("elems") or []:
            try:
                d6 = int(e[5]) if len(e) > 5 else None
                if dpy > 0 and has_dpy and d6 != dpy:
                    continue
                raw.append((int(e[1]), int(e[2]), str(e[3]), bool(e[4])))
            except Exception:
                continue
        clicks = [e for e in raw if e[3]][:80]
        texts = [e for e in raw if not e[3] and len(e[2]) >= 2][:40]
        return clicks + texts, None
    except Exception as e:
        return None, "bridge: %r" % (e,)


def collect_nodes(node, out, limit=120):
    if not isinstance(node, dict) or len(out) >= limit:
        return
    text = (node.get("text") or "").strip()
    desc = (node.get("contentDescription") or "").strip()
    label = text if text else desc
    clickable = bool(node.get("isClickable") or node.get("isLongClickable") or node.get("isEditable"))
    b = node.get("boundsInScreen") or {}
    if label and isinstance(b, dict) and b:
        cx = (b.get("left", 0) + b.get("right", 0)) // 2
        cy = (b.get("top", 0) + b.get("bottom", 0)) // 2
        out.append((cx, cy, label[:120], clickable))
    for c in node.get("children") or []:
        collect_nodes(c, out, limit)


def cmd_state():
    if DISPLAY and DISPLAY != "0":
        # 影子屏（正式模式）：portal 焦点会漂移 → 只认桥树（按 displayId 过滤）
        elems, err = bridge_elems(int(DISPLAY))
        if err:
            print("bridge_unavailable: %s" % err)
            print("(提示: 影子屏感知走桥树；桥离线时可先 key HOME 或等守护修复)")
            return 2
        print("front: (display %s, bridge tree) | elements: %d" % (DISPLAY, len(elems)))
        for x, y, label, cl in elems:
            print("(%d,%d) %s%s" % (x, y, label, " [可点]" if cl else ""))
        return 0
    try:
        d = _unwrap(portal("/state_full", timeout=25))
    except Exception as e:
        print("portal_unreachable: %r" % (e,))
        print("(提示: portal 可能掉线，可等 supervisor 自愈，或用 key HOME 先回桌面)")
        return 2
    ph = d.get("phone_state") or {}
    print("front: %s | app: %s | keyboard: %s | display: %s"
          % (ph.get("packageName"), ph.get("currentApp"), ph.get("keyboardVisible"), DISPLAY))
    out = []
    collect_nodes(d.get("a11y_tree") or {}, out)
    if not out:
        print("(空树：该应用屏蔽了无障碍读取（如微信）→ 请走 wx_send，或用 shot 截图后自行查看)")
        return 0
    for x, y, label, cl in out:
        print("(%d,%d) %s%s" % (x, y, label, " [可点]" if cl else ""))
    print("total: %d 个元素" % len(out))
    return 0


def cmd_tap(x, y):
    r = run(["/system/bin/input"] + _dprefix() + ["tap", str(int(x)), str(int(y))], 15)
    err = r.stderr.decode(errors="replace").strip()
    if r.returncode != 0 or "Error" in err or "Exception" in err:
        _unwrap(portal("/tap", {"x": int(x), "y": int(y)}))
        print("tap(%s,%s) via portal" % (x, y))
    else:
        print("tap(%s,%s) ok" % (x, y))
    return 0


def cmd_swipe(x1, y1, x2, y2, ms=500):
    r = run(["/system/bin/input"] + _dprefix()
            + ["swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(ms))], 20)
    err = r.stderr.decode(errors="replace").strip()
    if r.returncode != 0 or "Error" in err:
        _unwrap(portal("/swipe", {"startX": int(x1), "startY": int(y1),
                                  "endX": int(x2), "endY": int(y2), "duration": float(ms)}))
        print("swipe via portal")
    else:
        print("swipe ok (%sms)" % ms)
    return 0


def cmd_text(s):
    b64 = base64.b64encode(s.encode("utf-8")).decode()
    try:
        _unwrap(portal("/keyboard/input", {"base64_text": b64, "clear": False}))
        print("text ok (portal keyboard)")
        return 0
    except Exception as e:
        print("portal keyboard failed: %r; fallback input text（仅 ASCII）" % (e,), file=sys.stderr)
        run(["/system/bin/input"] + _dprefix() + ["text", s], 20)
        print("text ok (input)")
        return 0


KEYCODES = {"BACK": 4, "HOME": 3, "ENTER": 66, "TAB": 61, "DEL": 67, "SPACE": 62,
            "VOLUMEDOWN": 25, "VOLUMEUP": 24, "POWER": 26, "APP_SWITCH": 187, "ESCAPE": 111}


def cmd_key(name):
    name = str(name).upper()
    code = KEYCODES.get(name, name if str(name).isdigit() else None)
    if code is None:
        print("unknown key: %s (可用: %s)" % (name, ",".join(KEYCODES)))
        return 2
    r = run(["/system/bin/input"] + _dprefix() + ["keyevent", str(code)], 15)
    err = r.stderr.decode(errors="replace").strip()
    if r.returncode != 0 or "Error" in err:
        _unwrap(portal("/keyboard/key", {"key_code": int(code)}))
        print("key %s via portal" % name)
    else:
        print("key %s ok" % name)
    return 0


def _get_apps():
    d = _unwrap(portal("/packages", timeout=20))
    return d if isinstance(d, list) else []


def _resolve_pkg(name):
    name = str(name).strip()
    apps = _get_apps()
    for a in apps:  # 精确包名
        if str(a.get("packageName")) == name:
            return name
    for a in apps:  # 精确 label（取最短包名）
        if str(a.get("label", "")).strip() == name:
            same = [str(x.get("packageName")) for x in apps if str(x.get("label", "")).strip() == name]
            return sorted(same, key=len)[0]
    for a in apps:  # label 模糊
        if name and name in str(a.get("label", "")):
            return str(a.get("packageName"))
    return None


def cmd_open(name):
    pkg = _resolve_pkg(name)
    if not pkg:
        print("app_not_found: 未找到应用 %r（可用 ptool apps 查看）" % name)
        return 2
    if DISPLAY and DISPLAY != "0":
        # 影子屏：解析入口 Activity → am start --display N
        comp = ""
        r = run(["/system/bin/cmd", "package", "resolve-activity", "--brief", pkg], 15)
        for ln in reversed((r.stdout or b"").decode(errors="replace").strip().splitlines()):
            ln = ln.strip()
            if "/" in ln and " " not in ln:
                comp = ln
                break
        if not comp:
            print("open(shadow): 无法解析入口 Activity %s" % pkg)
            return 1
        r = run(["/system/bin/am", "start", "--display", DISPLAY, "-n", comp], 20)
        out = ((r.stdout or b"") + (r.stderr or b"")).decode(errors="replace").strip()
        ok = (r.returncode == 0 and "Error" not in out)
        print("open(shadow d%s): %s -> %s (%s)" % (DISPLAY, name, comp, "ok" if ok else out[:120]))
        return 0 if ok else 1
    ok = False
    try:
        _unwrap(portal("/app", {"package": pkg}))
        ok = True
    except Exception:
        ok = False
    if not ok:
        args = ["/system/bin/monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"]
        r = run(args, 20)
        ok = r.returncode == 0
    print("open: %s -> %s (%s)" % (name, pkg, "ok" if ok else "failed"))
    return 0 if ok else 1


def cmd_shot(path=None):
    os.makedirs(WORK_OUT, exist_ok=True)
    path = path or os.path.join(WORK_OUT, "shot-%d.png" % int(time.time()))
    r = run(["/system/bin/screencap", "-p", path], 30)
    if r.returncode != 0 or not os.path.exists(path):
        err = r.stderr.decode(errors="replace")
        print("shot failed: %s" % err)
        return 1
    size = os.path.getsize(path)
    if size < 1000:
        print("shot tiny (%dB): 可能遇到 FLAG_SECURE 页面" % size)
        return 1
    print("shot -> %s (%dB)" % (path, size))
    return 0


def cmd_battery():
    r = run(["/system/bin/dumpsys", "battery"], 20)
    txt = r.stdout.decode(errors="replace")
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith(("level", "status", "AC powered", "USB powered", "Wireless powered", "temperature")):
            print(s)
    return 0


def cmd_apps():
    apps = _get_apps()
    print("total: %d" % len(apps))
    for a in sorted(apps, key=lambda x: str(x.get("label", ""))):
        print("%s\t%s" % (a.get("label"), a.get("packageName")))
    return 0


def cmd_front():
    r = run(["/system/bin/dumpsys", "window"], 25)
    txt = r.stdout.decode(errors="replace")
    for line in txt.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            print(line.strip())
    return 0


def cmd_wx_send(to, text):
    os.makedirs(WORK_OUT, exist_ok=True)
    cmd = ["python3", os.path.join(HOME_DIR, "wx_send.py"),
           "--to", to, "--text", text,
           "--json-out", os.path.join(WORK_OUT, "wx_send_last.json")]
    r = run(cmd, t=240)
    sys.stdout.write(r.stdout.decode(errors="replace"))
    err = r.stderr.decode(errors="replace").strip()
    if err:
        print(err, file=sys.stderr)
    print("wx_send rc=%d" % r.returncode)
    return r.returncode


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    c = argv[0]
    try:
        if c == "state":
            return cmd_state()
        if c == "tap":
            return cmd_tap(argv[1], argv[2])
        if c == "swipe":
            return cmd_swipe(argv[1], argv[2], argv[3], argv[4],
                             argv[5] if len(argv) > 5 else 500)
        if c == "text":
            return cmd_text(argv[1])
        if c == "key":
            return cmd_key(argv[1])
        if c == "open":
            return cmd_open(argv[1])
        if c == "shot":
            return cmd_shot(argv[1] if len(argv) > 1 else None)
        if c == "battery":
            return cmd_battery()
        if c == "apps":
            return cmd_apps()
        if c == "front":
            return cmd_front()
        if c == "wx-send":
            to = text = None
            i = 1
            while i < len(argv):
                if argv[i] == "--to" and i + 1 < len(argv):
                    to = argv[i + 1]; i += 2
                elif argv[i] == "--text" and i + 1 < len(argv):
                    text = argv[i + 1]; i += 2
                else:
                    i += 1
            if not to or text is None:
                print("usage: ptool wx-send --to 名字 --text 内容")
                return 2
            return cmd_wx_send(to, text)
        print("unknown command: %s" % c)
        print(__doc__)
        return 2
    except Exception as e:
        print("ptool error: %r" % (e,))
        return 1


if __name__ == "__main__":
    sys.exit(main())
