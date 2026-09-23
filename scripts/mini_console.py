#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""mini_console.py — 手机本机控制台（"入口"）v2 · App 式界面

手机浏览器打开 http://127.0.0.1:8900/ —— 像手机 App 一样使用：
  · 底部输入条（说一句话就发）＋ 模式分段（智能 / 极速 / 深度）
  · 运行中实时步骤；完成后结果大卡片（可再跑一次 / 收藏）
  · 「常用」收藏：一键运行，长按删除
  · 「历史记录」：跑过的任务可回看、重跑、收藏
控制台以 root 常驻（不被 ColorOS 冻结），无需流量心跳。

端点：
  GET  /                    页面
  POST /api/run             {"task": str, "mode": "auto|jev|qwen"} → 启动任务
  GET  /api/status          当前任务状态 + 日志尾巴
  POST /api/stop            停止当前任务
  GET  /api/history         最近任务记录（含结果；自动清理"中途夭折"的 running 残留）
  GET  /api/favorites       收藏列表
  POST /api/favorites       {"task","mode"} → 收藏（同任务去重并置顶）
  POST /api/favorites/del   {"task"} → 取消收藏
依赖：纯标准库。
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
PREFIX = "/data/data/com.termux/files/usr"
AGENT = os.path.join(HOME, "mini_agent.py")
RUNS = os.path.join(HOME, "bridge", "runs")
OUTD = os.path.join(HOME, "bridge", "out")
LOG = os.path.join(OUTD, "console.log")
FAV_FILE = os.path.join(HOME, "bridge", "favorites.json")
DEBUG_FILE = os.path.join(HOME, "bridge", "debug.json")
HOTKEY_FILE = os.path.join(HOME, "bridge", "hotkey.json")
PORT = int(os.environ.get("CONSOLE_PORT", "8900"))
PING_URL = os.environ.get("LLM_PING", "http://192.168.3.75:8888/v1/models")

LOCK = threading.Lock()
RUN = {"id": None, "task": "", "mode": "", "proc": None, "out": None,
       "started": 0, "ended": 0, "state": "idle", "rc": None}
HB = {"last": 0, "llm": "-"}


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def llm_probe():
    """轻量探测"大脑"（局域网 LLM 端点）可达性，供界面顶栏显示。
    背景：防冻已由 root 常驻方案解决，不再需要过去的公网流量心跳（已移除）。"""
    while True:
        try:
            req = urllib.request.Request(PING_URL, headers={"Authorization": "Bearer 123"})
            urllib.request.urlopen(req, timeout=3).read(2048)
            HB["llm"] = "ok"
        except urllib.error.HTTPError:
            HB["llm"] = "ok"
        except Exception:
            HB["llm"] = "fail"
        HB["last"] = time.time()
        time.sleep(30)


def agent_env(rid=None):
    env = dict(os.environ)
    env["HOME"] = HOME
    env["PATH"] = PREFIX + "/bin:" + env.get("PATH", "/system/bin")
    env["LD_LIBRARY_PATH"] = PREFIX + "/lib"
    env.pop("AGENT_ENGINE", None)  # 引擎由 --engine 参数决定，避免环境串味
    if rid:
        # 每任务独立调试 trace（prompt/reply/action/result），供调试浮窗与复盘
        env["TRACE_PATH"] = os.path.join(RUNS, rid + ".trace.jsonl")
    return env


# ---------------------------------------------------------------- 收藏
def fav_load():
    try:
        with open(FAV_FILE, encoding="utf-8") as f:
            items = json.load(f)
        return [x for x in items if isinstance(x, dict) and x.get("task")]
    except Exception:
        return []


def fav_save(items):
    os.makedirs(os.path.dirname(FAV_FILE), exist_ok=True)
    with open(FAV_FILE, "w", encoding="utf-8") as f:
        json.dump(items[:20], f, ensure_ascii=False, indent=1)


def fav_add(task, mode):
    items = fav_load()
    items = [x for x in items if x.get("task") != task]
    items.insert(0, {"task": task, "mode": mode or "auto", "ts": time.time()})
    fav_save(items)
    return items


def fav_del(task):
    items = [x for x in fav_load() if x.get("task") != task]
    fav_save(items)
    return items


# ---------------------------------------------------------------- 调试（开关 + 执行链路）
def debug_get():
    try:
        with open(DEBUG_FILE, encoding="utf-8") as f:
            return bool(json.load(f).get("on"))
    except Exception:
        return False


def debug_set(on):
    try:
        os.makedirs(os.path.dirname(DEBUG_FILE), exist_ok=True)
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump({"on": bool(on)}, f)
    except Exception:
        pass
    return bool(on)


def hotkey_get():
    """音量键快捷唤起开关（默认开）"""
    try:
        with open(HOTKEY_FILE, encoding="utf-8") as f:
            return bool(json.load(f).get("on", True))
    except Exception:
        return True


def hotkey_set(on):
    try:
        os.makedirs(os.path.dirname(HOTKEY_FILE), exist_ok=True)
        with open(HOTKEY_FILE, "w", encoding="utf-8") as f:
            json.dump({"on": bool(on)}, f)
    except Exception:
        pass
    return bool(on)


def trace_read(rid=None, start=0, limit=500):
    """读某任务的执行链路（<rid>.trace.jsonl）。返回 {rid, lines, next, total}。"""
    if not rid:
        with LOCK:
            rid = RUN["id"]
    if not rid:
        return {"rid": None, "lines": [], "next": 0, "total": 0}
    path = os.path.join(RUNS, rid + ".trace.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.readlines()
    except Exception:
        return {"rid": rid, "lines": [], "next": 0, "total": 0}
    total = len(raw)
    chunk = raw[start:start + limit]
    out = []
    for ln in chunk:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            out.append({"kind": "text", "text": ln[:300]})
    return {"rid": rid, "lines": out, "next": start + len(chunk), "total": total}


# ---------------------------------------------------------------- 运行
def _meta_path(rid):
    return os.path.join(RUNS, rid + ".json")


def _save_meta(rid, extra=None):
    meta = {"id": rid, "task": RUN["task"], "mode": RUN["mode"],
            "started": RUN["started"], "ended": RUN["ended"], "rc": RUN["rc"],
            "state": RUN["state"]}
    if extra:
        meta.update(extra)
    try:
        with open(_meta_path(rid), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except Exception:
        pass


def start_run(task, mode):
    global RUN
    with LOCK:
        if RUN["state"] == "running":
            return None, "已有任务在跑"
        os.makedirs(RUNS, exist_ok=True)
        os.makedirs(OUTD, exist_ok=True)
        rid = datetime.now().strftime("%m%d-%H%M%S")
        out = os.path.join(RUNS, rid + ".out")
        f = open(out, "wb")
        cmd = [sys.executable or "python3", AGENT, task, "--engine", mode, "--max-steps", "25"]
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=agent_env(rid), cwd=HOME)
        RUN = {"id": rid, "task": task, "mode": mode, "proc": p, "out": out,
               "started": time.time(), "ended": 0, "state": "running", "rc": None}
        _save_meta(rid)
        log("run %s started: mode=%s task=%s" % (rid, mode, task))
        return rid, None


def stop_run():
    with LOCK:
        p = RUN["proc"]
        if RUN["state"] != "running" or p is None:
            return False
        try:
            p.terminate()
        except Exception:
            pass
        t0 = time.time()
        while p.poll() is None and time.time() - t0 < 2.5:
            time.sleep(0.1)
        if p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass
        RUN["state"] = "stopped"
        RUN["ended"] = time.time()
        RUN["rc"] = p.poll()
        _save_meta(RUN["id"])
        log("run %s stopped by user" % RUN["id"])
        return True


def _finalize_locked():
    p = RUN["proc"]
    if RUN["state"] == "running" and p is not None and p.poll() is not None:
        RUN["rc"] = p.returncode
        RUN["ended"] = time.time()
        RUN["state"] = "done" if p.returncode == 0 else "failed"
        info = parse_run(read_out(RUN["id"]))
        _save_meta(RUN["id"], {"result": info.get("result"), "engine": info.get("engine"),
                               "usage": info.get("usage"), "failed_reason": info.get("failed_reason")})
        log("run %s finished rc=%s" % (RUN["id"], p.returncode))


def read_out(rid, max_bytes=20000):
    if not rid:
        return []
    try:
        with open(os.path.join(RUNS, rid + ".out"), "rb") as f:
            data = f.read()[-max_bytes:]
        return data.decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def parse_run(lines):
    info = {"engine": None, "step": 0, "result": None, "failed_reason": None,
            "switches": [], "usage": None}
    for ln in lines:
        m = re.search(r"\[step (\d+)\] (\w+) ([\d.]+)s", ln)
        if m:
            info["step"] = int(m.group(1))
            info["engine"] = m.group(2)
        if "[switch]" in ln:
            info["switches"].append(ln.strip())
        m = re.search(r"\[agent\] DONE: (.*)", ln)
        if m:
            info["result"] = m.group(1).strip()
        if "max steps" in ln:
            info["failed_reason"] = "步数用尽"
        if "[agent] FAILED:" in ln:
            info["failed_reason"] = ln.split("FAILED:", 1)[1].strip()
        if "Traceback" in ln:
            info["failed_reason"] = "运行出错（见日志）"
        if "decide error" in ln or "exec error" in ln:
            info["failed_reason"] = "执行出错"
        m = re.search(r"\[agent\] engine-usage: (.*)", ln)
        if m:
            info["usage"] = m.group(1).strip()
    return info


def status_payload():
    with LOCK:
        _finalize_locked()
        rid = RUN["id"]
        state = RUN["state"]
        task = RUN["task"]
        mode = RUN["mode"]
        started = RUN["started"]
        ended = RUN["ended"]
        rc = RUN["rc"]
    elapsed = (ended or time.time()) - started if started else 0
    lines = read_out(rid)
    info = parse_run(lines)
    if state == "stopped":
        info["failed_reason"] = info.get("failed_reason") or "已手动停止"
    return {
        "state": state, "run_id": rid, "task": task, "mode": mode,
        "engine": info["engine"], "step": info["step"],
        "elapsed": elapsed, "result": info["result"],
        "failed_reason": info["failed_reason"], "switches": info["switches"],
        "usage": info["usage"], "lines": lines[-80:], "rc": rc,
        "hb": {"llm": HB["llm"],
               "age": round(time.time() - HB["last"], 1) if HB["last"] else None},
    }


def history_list(limit=24):
    out = []
    try:
        names = sorted((n for n in os.listdir(RUNS) if n.endswith(".json") and not n.startswith("_")),
                       reverse=True)
        for name in names:
            path = os.path.join(RUNS, name)
            try:
                with open(path, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            # 清理"中途夭折"的 running 残留：out 超过 3 分钟没更新即视为中断
            if meta.get("state") == "running":
                out_path = os.path.join(RUNS, name[:-5] + ".out")
                try:
                    mt = os.path.getmtime(out_path)
                except Exception:
                    mt = 0
                if time.time() - mt > 180:
                    meta["state"] = "failed"
                    meta.setdefault("failed_reason", "中断（控制台曾重启）")
                    try:
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(meta, f, ensure_ascii=False)
                    except Exception:
                        pass
            out.append(meta)
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out


PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content">
<meta name="theme-color" content="#0f6e56">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>手机助手</title>
<style>
:root{
  --bg:#eef3f1;--card:#ffffff;--fg:#15211d;--mut:#66766f;
  --acc:#0f6e56;--acc-soft:rgba(15,110,86,.10);--acc-bd:rgba(15,110,86,.35);
  --red:#c04a4a;--red-soft:rgba(192,74,74,.10);
  --bd:#e0e8e4;--shadow:0 1px 3px rgba(16,42,35,.07);
  --topbg:linear-gradient(135deg,#0f6e56,#128a6f);
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0f1514;--card:#181f1d;--fg:#e8f1ed;--mut:#8fa29b;
  --acc:#3cc39b;--acc-soft:rgba(60,195,155,.13);--acc-bd:rgba(60,195,155,.40);
  --red:#e07a7a;--red-soft:rgba(224,122,122,.12);
  --bd:#243029;--shadow:0 1px 3px rgba(0,0,0,.35);
  --topbg:linear-gradient(135deg,#0b3d31,#0e5344);
}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
button{font:inherit;color:inherit;cursor:pointer}
.topwrap{background:var(--topbg);padding-top:env(safe-area-inset-top)}
.topbar{max-width:640px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;padding:11px 14px 12px}
.brand{color:#fff;font-size:17px;font-weight:700;display:flex;align-items:center;gap:8px}
.brand .logo{font-size:19px}
.pill{display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.16);color:#fff;border-radius:999px;padding:4px 11px;font-size:12px;line-height:1.4}
.pill .dot{width:8px;height:8px;border-radius:50%;background:#a8f0d0;flex:none}
.pill .dot.warn{background:#ffd28f}
.pill .dot.bad{background:#ffb0b0}
main{max-width:640px;margin:0 auto;padding:14px 12px 196px}
.sec{margin-bottom:16px}
.sechead{display:flex;align-items:baseline;justify-content:space-between;margin:0 4px 8px}
.sectitle{font-size:14px;font-weight:700;letter-spacing:.02em}
.sechint{font-size:11.5px;color:var(--mut)}
.empty{color:var(--mut);font-size:13px;background:var(--card);border:1px dashed var(--bd);border-radius:14px;padding:14px;text-align:center}
.card{background:var(--card);border:1px solid var(--bd);border-radius:16px;box-shadow:var(--shadow)}

/* —— 常用（收藏） —— */
#favwrap{display:flex;gap:8px;overflow-x:auto;padding:2px 2px 6px;scrollbar-width:none}
#favwrap::-webkit-scrollbar{display:none}
.fav{flex:none;max-width:210px;border:1px solid var(--acc-bd);background:var(--acc-soft);color:var(--acc);
  border-radius:999px;padding:8px 15px;font-size:13.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fav:active{transform:scale(.96)}
.favwrap-empty{color:var(--mut);font-size:13px;padding:6px 4px}

/* —— 运行 / 结果 —— */
.rcard{padding:13px 14px}
.rtop{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.badge{font-size:11.5px;font-weight:700;border-radius:999px;padding:3px 10px}
.badge.run{background:var(--acc-soft);color:var(--acc)}
.badge.ok{background:var(--acc-soft);color:var(--acc)}
.badge.bad{background:var(--red-soft);color:var(--red)}
.rmeta{font-size:12px;color:var(--mut)}
.rtask{font-size:14px;font-weight:600;margin-bottom:2px;word-break:break-all}
.rlog{color:var(--mut);font:11.5px/1.55 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-all;
  max-height:150px;overflow:auto;margin:9px 0 0;padding:9px 10px;background:var(--bg);border-radius:10px}
.result{font-size:21px;font-weight:700;line-height:1.45;margin:6px 0 4px;white-space:pre-wrap;word-break:break-word}
.result.fail{color:var(--red)}
.ractions{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.rbtn{border:1px solid var(--bd);background:transparent;border-radius:999px;padding:8px 16px;font-size:13.5px;font-weight:600}
.rbtn.acc{border-color:var(--acc-bd);background:var(--acc-soft);color:var(--acc)}
.rbtn:active{transform:scale(.97)}
.idlebox{color:var(--mut);font-size:13.5px;padding:4px}
.idlebox b{color:var(--fg)}

/* —— 历史 —— */
#histlist{display:flex;flex-direction:column;gap:8px}
.hitem{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:10px 12px;box-shadow:var(--shadow)}
.hitem:active{background:var(--acc-soft)}
.htop{display:flex;align-items:center;gap:7px;margin-bottom:3px}
.htime{font-size:11.5px;color:var(--mut);flex:none}
.hbadge{font-size:11px;font-weight:700;border-radius:999px;padding:2px 8px;flex:none}
.hbadge.ok{background:var(--acc-soft);color:var(--acc)}
.hbadge.bad{background:var(--red-soft);color:var(--red)}
.hbadge.run{background:var(--acc-soft);color:var(--acc)}
.hres{font-size:12px;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hmain{display:flex;align-items:center;gap:8px}
.htask{flex:1;font-size:13.5px;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:break-all}
.hacts{display:flex;gap:4px;flex:none}
.hacts button{width:36px;height:36px;border:0;border-radius:10px;background:transparent;font-size:17px;color:var(--mut)}
.hacts button.staron{color:#d99a2b}
.hacts button:active{background:var(--acc-soft)}

/* —— 底部输入条 —— */
footer{position:fixed;left:0;right:0;bottom:0;z-index:30;pointer-events:none}
.fin{max-width:640px;margin:0 auto;padding:0 10px calc(10px + env(safe-area-inset-bottom));pointer-events:auto}
.modes{display:flex;gap:4px;background:var(--card);border:1px solid var(--bd);border-radius:999px;padding:3px;width:max-content;margin:0 auto 7px;box-shadow:var(--shadow)}
.mode{border:0;background:transparent;color:var(--mut);border-radius:999px;padding:6px 15px;font-size:12.5px;font-weight:600}
.mode.on{background:var(--acc);color:#fff}
.inputrow{display:flex;gap:8px;align-items:flex-end;background:var(--card);border:1px solid var(--bd);
  border-radius:24px;padding:5px 5px 5px 14px;box-shadow:0 4px 18px rgba(10,30,25,.14)}
@media (prefers-color-scheme:dark){.inputrow{box-shadow:0 4px 18px rgba(0,0,0,.5)}}
#task{flex:1;border:0;outline:0;background:transparent;color:var(--fg);font:16px/1.5 inherit;
  resize:none;max-height:118px;padding:9px 0 9px;overflow-y:auto}
#task::placeholder{color:var(--mut)}
.go{width:44px;height:44px;border:0;border-radius:50%;background:var(--acc);color:#fff;font-size:19px;
  flex:none;display:flex;align-items:center;justify-content:center;transition:transform .08s}
.go:active{transform:scale(.93)}
.go.stop{background:var(--red)}
.go:disabled{opacity:.45}
#hint{display:none;text-align:center;color:var(--red);font-size:12.5px;padding:8px 12px 0}
.dbgbtn{width:34px;height:34px;border:0;border-radius:50%;background:rgba(255,255,255,.16);color:#fff;font-size:15px;display:flex;align-items:center;justify-content:center;flex:none}
.dbgbtn.on{background:#ffd166;box-shadow:0 0 0 2px rgba(255,209,102,.45)}
#tracebox{display:none;position:fixed;inset:0;z-index:60;background:rgba(8,18,14,.55);padding:18px 12px}
#tracebox.show{display:flex;align-items:center;justify-content:center}
.tcard{background:var(--card);border:1px solid var(--bd);border-radius:16px;width:100%;max-width:640px;max-height:84vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:var(--shadow)}
.thead{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;font-size:13.5px;font-weight:700;border-bottom:1px solid var(--bd)}
.thead .tx{color:var(--mut);font-size:11.5px;font-weight:400;margin-left:8px}
.thead button{border:0;background:transparent;font-size:16px;color:var(--mut);width:34px;height:34px;border-radius:10px}
.thead button:active{background:var(--acc-soft)}
#tracepre{flex:1;overflow:auto;margin:0;padding:12px 14px;font:11.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-all;color:var(--fg)}
#toast{position:fixed;left:50%;bottom:196px;transform:translateX(-50%);z-index:70;background:rgba(18,38,31,.93);color:#fff;font-size:12.5px;padding:9px 16px;border-radius:999px;display:none;max-width:86%;text-align:center}
</style>
</head>
<body>

<div class="topwrap">
  <div class="topbar">
    <div class="brand"><span class="logo">📱</span>手机助手</div>
    <div style="display:flex;align-items:center;gap:8px">
      <button id="hkbtn" class="dbgbtn" title="音量键快捷键（点按开关）">⌨</button>
      <button id="dbgbtn" class="dbgbtn" title="调试模式（点按开关）">🐞</button>
      <div class="pill"><span class="dot" id="dot"></span><span id="nettext">连接中</span></div>
    </div>
  </div>
</div>

<main>
  <section class="sec">
    <div class="sechead"><span class="sectitle">⭐ 常用</span><span class="sechint">点一下就跑 · 长按删除</span></div>
    <div id="favwrap"><div class="favwrap-empty">把常做的任务收藏到这里（历史记录里点 ☆ 收藏）</div></div>
  </section>

  <section class="sec" id="runsec">
    <div class="sechead"><span class="sectitle" id="runttl">🏠 当前任务</span></div>
    <div class="card rcard" id="runcard">
      <div class="idlebox">还没有运行中的任务。<b>说一句话</b>，让手机自己去做 👇</div>
    </div>
  </section>

  <section class="sec">
    <div class="sechead"><span class="sectitle">🕐 历史记录</span><span class="sechint">点任务可填入输入框</span></div>
    <div id="histlist"><div class="empty">跑过的任务会出现在这里</div></div>
  </section>
</main>

<div id="tracebox">
  <div class="tcard">
    <div class="thead">
      <span>🔗 执行链路<span class="tx">prompt / 回复 / 动作 / 结果</span></span>
      <button id="traceclose">✕</button>
    </div>
    <pre id="tracepre">加载中…</pre>
  </div>
</div>
<div id="toast"></div>

<footer>
  <div class="fin">
    <div class="modes" id="modes">
      <button class="mode on" data-m="auto">智能</button>
      <button class="mode" data-m="jev">极速</button>
      <button class="mode" data-m="qwen">深度</button>
    </div>
    <div class="inputrow">
      <textarea id="task" rows="1" enterkeyhint="send"
        placeholder="想让手机做什么？说一句话就行…"></textarea>
      <button class="go" id="btn-go" aria-label="发送">➤</button>
    </div>
    <div id="hint">连不上服务：打开一次 Termux 可恢复；仍不行请在 Termux 重跑 run.sh。</div>
  </div>
</footer>

<script>
var MODE = 'auto', POLL = null, ST = {state:'idle'}, FAVS = [];
function $(s){ return document.querySelector(s); }
function $$(s){ return [].slice.call(document.querySelectorAll(s)); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function two(n){ return (n < 10 ? '0' : '') + n; }
function fmtTime(ts){
  if(!ts) return '';
  var d = new Date(ts * 1000), now = new Date();
  var same = d.toDateString() === now.toDateString();
  return (same ? '' : (two(d.getMonth()+1) + '-' + two(d.getDate()) + ' ')) + two(d.getHours()) + ':' + two(d.getMinutes());
}
function trunc(s, n){ s = String(s||''); return s.length > n ? s.slice(0, n) + '…' : s; }
function isFav(task){ for(var i=0;i<FAVS.length;i++){ if(FAVS[i].task === task) return true; } return false; }

/* ---------- 顶栏状态 ---------- */
function setNet(ok, d){
  var dot = $('#dot'), tx = $('#nettext');
  if(!ok){ dot.className = 'dot bad'; tx.textContent = '服务离线'; return; }
  var llm = d && d.hb ? d.hb.llm : '-';
  if(llm === 'ok'){ dot.className = 'dot'; tx.textContent = '大脑在线'; }
  else if(llm === 'fail'){ dot.className = 'dot warn'; tx.textContent = '大脑未连上'; }
  else { dot.className = 'dot'; tx.textContent = '在线'; }
}

/* ---------- 模式 ---------- */
function setMode(m){
  MODE = m;
  $$('.mode').forEach(function(b){ b.classList.toggle('on', b.dataset.m === m); });
}
$$('.mode').forEach(function(b){ b.addEventListener('click', function(){ setMode(b.dataset.m); }); });

/* ---------- 输入框 ---------- */
var ta = $('#task');
function autosize(){
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 118) + 'px';
}
ta.addEventListener('input', autosize);
ta.addEventListener('keydown', function(e){
  if(e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229){
    e.preventDefault(); pressGo();
  }
});

/* ---------- 发送 / 停止 ---------- */
function pressGo(){
  if(ST.state === 'running'){ stopTask(); } else { sendTask(ta.value, MODE); }
}
$('#btn-go').addEventListener('click', pressGo);

function sendTask(text, mode){
  text = String(text||'').trim();
  if(!text){ ta.focus(); return; }
  if(ST.state === 'running'){ flash('已有任务在跑'); return; }
  $('#hint').style.display = 'none';
  fetch('api/run', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task: text, mode: mode || MODE})})
  .then(function(r){ return r.json(); })
  .then(function(d){
    if(d.error){ flash('启动失败：' + d.error); return; }
    ta.value = ''; autosize();
    document.getElementById('runsec').scrollIntoView({behavior:'smooth', block:'start'});
    startPoll(true);
  })
  .catch(function(){ showHint(); });
}
function stopTask(){
  fetch('api/stop', {method:'POST'}).catch(function(){});
}
var flashT = null;
function flash(msg){
  var h = $('#hint'); h.textContent = msg; h.style.display = 'block';
  if(flashT) clearTimeout(flashT);
  flashT = setTimeout(function(){ h.style.display = 'none'; h.textContent = ''; }, 2500);
}
function showHint(){
  $('#hint').style.display = 'block';
  if(flashT) clearTimeout(flashT);
  flashT = setTimeout(function(){ $('#hint').style.display = 'none'; }, 6000);
}

/* ---------- 状态轮询 ---------- */
function startPoll(){
  if(POLL) clearInterval(POLL);
  POLL = setInterval(tick, 1200);
  tick();
}
function tick(){
  fetch('api/status').then(function(r){ return r.json(); }).then(function(d){
    ST = d;
    setNet(true, d);
    renderRun(d);
    var running = d.state === 'running';
    var btn = $('#btn-go');
    btn.classList.toggle('stop', running);
    btn.textContent = running ? '■' : '➤';
    if(running){ if(!POLL){ POLL = setInterval(tick, 1200); } }
    else {
      if(POLL){ clearInterval(POLL); POLL = null; }
      if(d.state === 'done' || d.state === 'failed' || d.state === 'stopped'){ loadHistory(); }
    }
  }).catch(function(){
    setNet(false);
  });
}

/* ---------- 运行卡 ---------- */
function renderRun(d){
  var card = $('#runcard'), ttl = $('#runttl');
  if(d.state === 'running'){
    ttl.textContent = '⚡ 运行中';
    var meta = '引擎 ' + (d.engine || '…') + ' · 第 ' + (d.step || 0) + ' 步 · ' + Math.round(d.elapsed || 0) + 's';
    card.innerHTML = '<div class="rtop"><span class="badge run">运行中</span><span class="rmeta">' + esc(meta) + '</span>'
      + '<button class="rbtn" id="btn-trace-run" style="margin-left:auto;padding:5px 13px;font-size:12px">🔗 链路</button></div>'
      + '<div class="rtask">' + esc(d.task) + '</div>'
      + '<pre class="rlog">' + esc((d.lines || []).slice(-12).join('\n')) + '</pre>';
    var rl = card.querySelector('.rlog'); if(rl){ rl.scrollTop = rl.scrollHeight; }
    var bt = card.querySelector('#btn-trace-run'); if(bt){ bt.onclick = function(){ showTrace(d.run_id); }; }
    return;
  }
  if(d.state === 'done' || d.state === 'failed' || d.state === 'stopped'){
    var ok = d.state === 'done';
    ttl.textContent = ok ? '✅ 完成' : (d.state === 'stopped' ? '⏹ 已停止' : '⚠️ 未完成');
    var head = '<div class="rtop"><span class="badge ' + (ok ? 'ok' : 'bad') + '">'
      + (ok ? '完成' : (d.state === 'stopped' ? '已停止' : '未完成')) + '</span>'
      + '<span class="rmeta">' + Math.round(d.elapsed || 0) + 's'
      + (d.engine ? ' · 引擎 ' + esc(d.engine) : '')
      + (d.usage ? ' · ' + esc(d.usage) : '') + '</span></div>'
      + '<div class="rtask">' + esc(d.task) + '</div>';
    var body = '';
    if(d.result){ body += '<div class="result' + (ok ? '' : ' fail') + '">' + esc(d.result) + '</div>'; }
    else if(!ok && d.failed_reason){ body += '<div class="result fail" style="font-size:15px">' + esc(d.failed_reason) + '</div>'; }
    var faved = isFav(d.task);
    body += '<div class="ractions">'
      + '<button class="rbtn acc" id="btn-again">↻ 再跑一次</button>'
      + '<button class="rbtn' + (faved ? ' acc' : '') + '" id="btn-fav">' + (faved ? '★ 已收藏' : '☆ 收藏') + '</button>'
      + '<button class="rbtn" id="btn-trace-done">🔗 链路</button>'
      + '</div>';
    card.innerHTML = head + body;
    var bAgain = card.querySelector('#btn-again'), bFav = card.querySelector('#btn-fav');
    if(bAgain) bAgain.onclick = function(){ sendTask(d.task, d.mode); };
    if(bFav) bFav.onclick = function(){ toggleFav(d.task, d.mode); };
    var bTr = card.querySelector('#btn-trace-done'); if(bTr){ bTr.onclick = function(){ showTrace(d.run_id); }; }
    return;
  }
  ttl.textContent = '🏠 当前任务';
  card.innerHTML = '<div class="idlebox">还没有运行中的任务。<b>说一句话</b>，让手机自己去做 👇</div>';
}

/* ---------- 收藏 ---------- */
function loadFavs(){
  fetch('api/favorites').then(function(r){ return r.json(); }).then(function(d){
    FAVS = d.items || [];
    renderFavs();
  }).catch(function(){});
}
function renderFavs(){
  var el = $('#favwrap');
  if(!FAVS.length){
    el.innerHTML = '<div class="favwrap-empty">把常做的任务收藏到这里（历史记录里点 ☆ 收藏）</div>';
    return;
  }
  el.innerHTML = FAVS.map(function(f){
    return '<button class="fav" data-task="' + esc(f.task) + '" data-mode="' + esc(f.mode || 'auto') + '" title="' + esc(f.task) + '">'
      + esc(trunc(f.task, 12)) + '</button>';
  }).join('');
}
function toggleFav(task, mode){
  var has = isFav(task);
  var url = has ? 'api/favorites/del' : 'api/favorites';
  fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({task: task, mode: mode || MODE})})
  .then(function(r){ return r.json(); })
  .then(function(){
    loadFavs();
    renderRun(ST);
  }).catch(function(){});
}
/* 收藏 chips：点一下就跑；长按删除 */
var lpT = null, lpFired = false;
var favWrap = $('#favwrap');
favWrap.addEventListener('pointerdown', function(e){
  var c = e.target.closest('.fav'); if(!c) return;
  lpFired = false;
  lpT = setTimeout(function(){
    lpFired = true;
    if(confirm('删除这个常用？\n「' + c.dataset.task + '」')){ toggleFav(c.dataset.task, c.dataset.mode); }
  }, 550);
});
['pointerup','pointerleave','pointercancel'].forEach(function(ev){
  favWrap.addEventListener(ev, function(){ if(lpT){ clearTimeout(lpT); lpT = null; } });
});
favWrap.addEventListener('click', function(e){
  var c = e.target.closest('.fav'); if(!c) return;
  if(lpFired){ e.preventDefault(); return; }
  sendTask(c.dataset.task, c.dataset.mode);
});

/* ---------- 历史 ---------- */
function loadHistory(){
  fetch('api/history').then(function(r){ return r.json(); }).then(function(items){
    var el = $('#histlist');
    if(!items || !items.length){ el.innerHTML = '<div class="empty">跑过的任务会出现在这里</div>'; return; }
    el.innerHTML = items.map(function(it, idx){
      var st = it.state === 'done' ? 'ok' : (it.state === 'running' ? 'run' : 'bad');
      var stx = it.state === 'done' ? '完成' : (it.state === 'running' ? '运行中' : (it.state === 'stopped' ? '已停止' : '未完成'));
      var res = it.result ? ('→ ' + trunc(it.result, 30)) : (it.failed_reason ? ('→ ' + trunc(it.failed_reason, 30)) : '');
      return '<div class="hitem" data-idx="' + idx + '">'
        + '<div class="htop"><span class="htime">' + esc(fmtTime(it.started)) + '</span>'
        + '<span class="hbadge ' + st + '">' + stx + '</span>'
        + '<span class="hres">' + esc(res) + '</span></div>'
        + '<div class="hmain"><span class="htask">' + esc(it.task || '') + '</span>'
        + '<span class="hacts">'
        + '<button class="hstar' + (isFav(it.task) ? ' staron' : '') + '" data-act="star">' + (isFav(it.task) ? '★' : '☆') + '</button>'
        + '<button data-act="replay">↻</button>'
        + '</span></div></div>';
    }).join('');
    el._items = items;
  }).catch(function(){});
}
$('#histlist').addEventListener('click', function(e){
  var item = e.target.closest('.hitem'); if(!item) return;
  var data = $('#histlist')._items || [];
  var it = data[Number(item.dataset.idx)]; if(!it) return;
  var act = e.target.closest('button');
  if(act){
    if(act.dataset.act === 'star'){ toggleFav(it.task, it.mode); return; }
    if(act.dataset.act === 'replay'){ sendTask(it.task, it.mode); return; }
    return;
  }
  ta.value = it.task || ''; autosize(); ta.focus();
});

/* ---------- 调试模式（🐞 开关 + 执行链路查看） ---------- */
var DBG = false;
function toastMsg(t){
  var el = $('#toast'); if(!el) return;
  el.textContent = t; el.style.display = 'block';
  clearTimeout(toastMsg._t);
  toastMsg._t = setTimeout(function(){ el.style.display = 'none'; }, 2600);
}
function renderDbg(){
  var b = $('#dbgbtn'); if(!b) return;
  b.className = 'dbgbtn' + (DBG ? ' on' : '');
  b.title = DBG ? '调试模式：已开（手机上将出现半透明调试窗）' : '调试模式：已关（点按开启）';
}
function setDbg(on, silent){
  fetch('api/debug', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({on: on})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      DBG = !!d.on; renderDbg();
      if(!silent){
        toastMsg(DBG ? '调试已开：手机上将出现半透明调试窗；本页点「🔗 链路」看完整细节'
                     : '调试已关');
      }
    })
    .catch(function(){ if(!silent) toastMsg('设置失败（服务离线？）'); });
}
$('#dbgbtn').onclick = function(){ setDbg(!DBG); };
fetch('api/debug').then(function(r){ return r.json(); })
  .then(function(d){ DBG = !!d.on; renderDbg(); }).catch(function(){});

/* —— 音量键快捷键开关（默认开：按一下唤起面板 / 再按一下执行） —— */
var HK = true;
function renderHk(){
  var b = $('#hkbtn'); if(!b) return;
  b.className = 'dbgbtn' + (HK ? ' on' : '');
  b.title = HK ? '音量键快捷键：已开（按一下唤起 / 再按执行）' : '音量键快捷键：已关（音量键恢复普通调节）';
}
$('#hkbtn').onclick = function(){
  fetch('api/hotkey', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({on: !HK})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      HK = !!d.on; renderHk();
      toastMsg(HK ? '音量键快捷键已开：按一下「音量下」唤起面板，再按一下执行'
                  : '音量键快捷键已关（音量键恢复普通调节）');
    })
    .catch(function(){ toastMsg('设置失败（服务离线？）'); });
};
fetch('api/hotkey').then(function(r){ return r.json(); })
  .then(function(d){ HK = !!d.on; renderHk(); }).catch(function(){});

var traceFrom = 0, traceRid = null;
function showTrace(rid){
  traceRid = rid || null;
  traceFrom = 0;
  $('#tracepre').textContent = '加载中…';
  $('#tracebox').classList.add('show');
  loadTrace(true);
}
function closeTrace(){ $('#tracebox').classList.remove('show'); }
$('#traceclose').onclick = closeTrace;
$('#tracebox').onclick = function(e){ if(e.target === $('#tracebox')) closeTrace(); };
function fmtTrace(lines){
  var out = [];
  lines.forEach(function(r){
    var k = r.kind || 'text';
    var tag = {prompt:'▶ 输入(prompt)', reply:'◀ 返回(reply)', action:'⚡ 动作',
               result:'✓ 结果', done:'🏁 完成'}[k] || k;
    var head = (r.step ? ('第' + r.step + '步 ') : '') + tag + (r.engine ? (' [' + r.engine + ']') : '');
    if(r.ms != null){ head += ' ' + r.ms + 'ms'; }
    if(r.ok === false){ head += ' ✗'; }
    var txt = String(r.text == null ? '' : r.text);
    if(txt.length > 700){ txt = txt.slice(0, 700) + ' …'; }
    out.push(head + '\n' + txt);
  });
  return out.join('\n\n');
}
function loadTrace(reset){
  var url = 'api/trace?limit=1000&from=' + (reset ? 0 : traceFrom)
    + (traceRid ? ('&rid=' + encodeURIComponent(traceRid)) : '');
  fetch(url).then(function(r){ return r.json(); })
    .then(function(d){
      if(reset){ $('#tracepre').textContent = ''; }
      if(!d.lines || !d.lines.length){
        if(reset){ $('#tracepre').textContent = '（这条任务还没有链路记录）'; }
        return;
      }
      traceFrom = d.next || (traceFrom + d.lines.length);
      var pre = $('#tracepre');
      pre.textContent += (pre.textContent ? '\n\n' : '') + fmtTrace(d.lines);
      pre.scrollTop = pre.scrollHeight;
    })
    .catch(function(){ if(reset){ $('#tracepre').textContent = '加载失败（服务离线？）'; } });
}

/* ---------- 启动 ---------- */
loadFavs();
loadHistory();
fetch('api/status').then(function(r){ return r.json(); }).then(function(d){
  ST = d; setNet(true, d); renderRun(d);
  if(d.state === 'running'){ startPoll(true); }
}).catch(function(){ setNet(false); });
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        if p in ("/", "/index.html"):
            self._send(200, PAGE_HTML, "text/html; charset=utf-8")
        elif p == "/api/status":
            self._send(200, json.dumps(status_payload(), ensure_ascii=False))
        elif p == "/api/history":
            self._send(200, json.dumps(history_list(), ensure_ascii=False))
        elif p == "/api/favorites":
            self._send(200, json.dumps({"items": fav_load()}, ensure_ascii=False))
        elif p == "/api/debug":
            self._send(200, json.dumps({"on": debug_get()}))
        elif p == "/api/hotkey":
            self._send(200, json.dumps({"on": hotkey_get()}))
        elif p == "/api/trace":
            rid = (q.get("rid") or [None])[0]
            try:
                start = int((q.get("from") or ["0"])[0])
            except ValueError:
                start = 0
            try:
                limit = min(1000, int((q.get("limit") or ["500"])[0]))
            except ValueError:
                limit = 500
            self._send(200, json.dumps(trace_read(rid, start, limit), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except Exception:
            body = {}
        if p == "/api/run":
            task = (body.get("task") or "").strip()
            mode = (body.get("mode") or "auto").strip().lower()
            if mode not in ("auto", "jev", "qwen"):
                mode = "auto"
            if not task:
                self._send(400, json.dumps({"error": "任务为空"}))
                return
            rid, err = start_run(task, mode)
            if err:
                self._send(409, json.dumps({"error": err}))
            else:
                self._send(200, json.dumps({"ok": True, "run_id": rid}))
        elif p == "/api/stop":
            self._send(200, json.dumps({"ok": stop_run()}))
        elif p == "/api/favorites":
            task = (body.get("task") or "").strip()
            mode = (body.get("mode") or "auto").strip().lower()
            if not task:
                self._send(400, json.dumps({"error": "task 为空"}))
                return
            self._send(200, json.dumps({"ok": True, "items": fav_add(task, mode)}, ensure_ascii=False))
        elif p == "/api/favorites/del":
            task = (body.get("task") or "").strip()
            self._send(200, json.dumps({"ok": True, "items": fav_del(task)}, ensure_ascii=False))
        elif p == "/api/debug":
            self._send(200, json.dumps({"ok": True, "on": debug_set(bool(body.get("on")))}))
        elif p == "/api/hotkey":
            self._send(200, json.dumps({"ok": True, "on": hotkey_set(bool(body.get("on")))}))
        else:
            self._send(404, json.dumps({"error": "not found"}))


class Srv(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return  # 连接被掐断是常态（轮询/页面关闭），不刷日志
        log("server error: %r" % (exc,))


def main():
    os.makedirs(RUNS, exist_ok=True)
    os.makedirs(OUTD, exist_ok=True)
    t = threading.Thread(target=llm_probe, daemon=True)
    t.start()
    srv = Srv(("127.0.0.1", PORT), Handler)
    log("console v2 listening on 127.0.0.1:%d" % PORT)
    print("console v2 on http://127.0.0.1:%d/" % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
