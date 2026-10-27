#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""atlas_scan.py —「App 地图」v1 扫描器（测试模式：全程在主屏可见地跑）

策略（hub-and-spoke，稳）：把 App 冷启到首页 → 快照（元素清单）→ 逐个点击"安全候选"
→ 记录新页面与跳转边；再对 1 个二级枢纽（如微博「发现」）重复一轮。
数据入数据仓 ~/bridge/store.db 的 atlas_pages / atlas_elements / atlas_edges 三表。

用法: python3 atlas_scan.py <package> [hub标签] [首页扫描数]
例:   python3 atlas_scan.py com.sina.weibo 发现 8
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
DB = os.path.join(HOME, "bridge", "store.db")
TREE = os.path.join(HOME, "bridge", ".tree.json")
REQ = os.path.join(HOME, "bridge", ".xgt_req")
RES = os.path.join(HOME, "bridge", ".xgt_res")
OUT = os.path.join(HOME, "bridge", "atlas")

# 敏感/危险词：候选点一律跳过（扫描期不碰钱、不碰账号、不碰删除）
DANGER = ("支付", "付款", "购买", "下单", "充值", "提现", "转账", "删除", "清空", "退出",
          "注销", "解绑", "卸载", "更新", "升级", "登录", "注册", "授权", "同意", "隐私",
          "权限", "签约", "开卡", "借钱", "贷款", "买入", "卖出", "撤单", "委托", "解绑")
DISMISS = ("跳过", "关闭", "知道了", "下次再说", "以后再说")


def clean_env():
    e = dict(os.environ)
    e.pop("LD_LIBRARY_PATH", None)
    e.pop("LD_PRELOAD", None)
    return e


def run(args, timeout=25):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=clean_env())
    except Exception as e:
        class R:
            stdout = ""
            stderr = repr(e)
            returncode = -1
        return R()


def bridge(cmd, timeout=8):
    seq = "a%d" % int(time.time() * 1000)
    try:
        os.remove(RES)
    except OSError:
        pass
    with open(REQ, "w", encoding="utf-8") as f:
        f.write("%s %s" % (seq, cmd))
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s = open(RES, encoding="utf-8").read().strip()
            if s:
                return s
        except OSError:
            pass
        time.sleep(0.05)
    return "err: timeout"


def elems(timeout=8):
    """主屏元素清单（扫描期间影子屏已关，树里就是主屏）。"""
    try:
        os.remove(TREE)
    except OSError:
        pass
    r = bridge("tree", timeout=timeout)
    if not r.startswith("ok"):
        return []
    try:
        d = json.load(open(TREE, encoding="utf-8", errors="replace"))
    except Exception:
        return []
    out = []
    for e in d.get("elems") or []:
        try:
            out.append({"label": str(e[3]), "x": int(e[1]), "y": int(e[2]), "clk": bool(e[4])})
        except Exception:
            pass
    return out


def tap(x, y):
    run(["/system/bin/input", "tap", str(int(x)), str(int(y))])


def key(code):
    run(["/system/bin/input", "keyevent", str(code)])


def current_focus():
    for cmd in (["/system/bin/dumpsys", "window"], ["/system/bin/dumpsys", "window", "displays"]):
        s = (run(cmd).stdout or "")
        m = re.search(r"mCurrentFocus=Window\{[^}]*?\bu0\s+([A-Za-z0-9_\.]+)/([A-Za-z0-9_\.\$]+)", s)
        if not m:
            m = re.search(r"mFocusedApp=ActivityRecord\{[^}]*?\bu0\s+([A-Za-z0-9_\.]+)/([A-Za-z0-9_\.\$]+)", s)
        if m:
            return (m.group(1), m.group(2))
    return ("", "")


def wait_stable(min_elems=8, timeout=15.0, step=1.0):
    """轮询元素清单直到页面稳定（元素数达标）或超时；返回最后一次元素清单。"""
    t0 = time.time()
    es = []
    while time.time() - t0 < timeout:
        es = elems()
        if len(es) >= min_elems:
            return es
        time.sleep(step)
    return es


def start_app(pkg):
    r = run(["/system/bin/cmd", "package", "resolve-activity", "--brief", pkg])
    comp = ""
    for ln in reversed((r.stdout or "").strip().splitlines()):
        ln = ln.strip()
        if "/" in ln and " " not in ln:
            comp = ln
            break
    if comp:
        run(["/system/bin/am", "start", "-n", comp])
        return True
    return False


def reset_home(pkg, wait=5.0):
    """冷启到首页；点掉开屏的「跳过/关闭」；App 若"恢复上次页面"则点底部「首页」回真首页；
    等页面真正有内容（≥8 元素）。返回是否成功。"""
    run(["/system/bin/am", "force-stop", pkg])
    time.sleep(1.2)
    if not start_app(pkg):
        return False
    time.sleep(wait)
    for _ in range(3):
        es = wait_stable(min_elems=8, timeout=6)
        hit = None
        for e in es:
            if e["clk"] and e["label"].strip() in DISMISS and e["y"] > 900:
                hit = e
                break
        if not hit:
            break
        tap(hit["x"], hit["y"])
        time.sleep(1.8)
    es = wait_stable(min_elems=8, timeout=6)
    for e in es:
        l = e["label"].strip()
        if e["clk"] and l.startswith("首页") and e["y"] > 2140:
            tap(e["x"], e["y"])
            time.sleep(2.2)
            break
    return True


def sig_of(pkg, act, es):
    # 只用「可点标签」做指纹：纯文字标签随内容/时间变化，可点标签更接近页面结构
    labs = sorted({e["label"][:24] for e in es if e["label"] and e["clk"]})
    h = 5381
    for l in labs[:40]:
        for ch in l:
            h = ((h * 33) + ord(ch)) & 0x7fffffff
    return "%s|%s|%08x" % (pkg.split(".")[-1], (act or "").split(".")[-1][:20], h)


NOISE_PREFIX = ("转发", "评论", "赞", "分享", "收藏", "举报", "不感兴趣", "投诉", "下载", "回复", "关注")


def safe_candidates(es, limit=6):
    out, seen = [], set()
    for e in es:
        if not e["clk"]:
            continue
        l = e["label"].strip()
        if not (2 <= len(l) <= 14):
            continue
        if any(w in l for w in DANGER):
            continue
        if l.startswith(NOISE_PREFIX) or "广告" in l:
            continue
        if e["y"] < 150 or e["y"] > 2290:
            continue
        if l in seen:
            continue
        seen.add(l)
        out.append(e)
        if len(out) >= limit:
            break
    return out


def db_conn():
    c = sqlite3.connect(DB, timeout=8)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS atlas_pages(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      package TEXT, activity TEXT, sig TEXT, title TEXT, elems INTEGER, ts REAL);
    CREATE TABLE IF NOT EXISTS atlas_elements(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      package TEXT, sig TEXT, label TEXT, x INTEGER, y INTEGER, clk INTEGER, ts REAL);
    CREATE TABLE IF NOT EXISTS atlas_edges(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      package TEXT, from_sig TEXT, label TEXT, x INTEGER, y INTEGER, to_sig TEXT, ts REAL);
    CREATE INDEX IF NOT EXISTS ix_at_pkg ON atlas_pages(package);
    CREATE INDEX IF NOT EXISTS ix_at_el ON atlas_elements(package);
    CREATE INDEX IF NOT EXISTS ix_at_ed ON atlas_edges(package);
    """)
    return c


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    pkg = sys.argv[1]
    hub = sys.argv[2] if len(sys.argv) > 2 else ""
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    os.makedirs(OUT, exist_ok=True)
    conn = db_conn()
    # 本次扫描重写该 App 的地图（v1 不做增量）
    for t in ("atlas_pages", "atlas_elements", "atlas_edges"):
        conn.execute("DELETE FROM %s WHERE package=?" % t, (pkg,))
    conn.commit()

    dump = {"package": pkg, "pages": [], "edges": []}
    seen_sigs = set()

    def record(es, act, tag):
        s = sig_of(pkg, act, es)
        if s not in seen_sigs:
            seen_sigs.add(s)
            conn.execute("INSERT INTO atlas_pages(package,activity,sig,title,elems,ts) VALUES(?,?,?,?,?,?)",
                         (pkg, act, s, (es[0]["label"][:40] if es else ""), len(es), time.time()))
            for e in es[:150]:
                conn.execute("INSERT INTO atlas_elements(package,sig,label,x,y,clk,ts) VALUES(?,?,?,?,?,?,?)",
                             (pkg, s, e["label"][:120], e["x"], e["y"], 1 if e["clk"] else 0, time.time()))
            conn.commit()
            dump["pages"].append({"sig": s, "activity": act, "tag": tag,
                                  "elems": len(es), "labels": [e["label"][:30] for e in es[:18]]})
        return s

    def edge(fs, label, x, y, ts_sig):
        conn.execute("INSERT INTO atlas_edges(package,from_sig,label,x,y,to_sig,ts) VALUES(?,?,?,?,?,?,?)",
                     (pkg, fs, label, int(x), int(y), ts_sig, time.time()))
        conn.commit()
        dump["edges"].append({"from": fs, "label": label, "to": ts_sig})

    def hub_pass(hub_label, budget):
        """回首页（或点进 hub）→ 逐个安全候选点击 → 记录。"""
        print("[atlas] ===== hub=%s =====" % (hub_label or "首页"))
        if not reset_home(pkg):
            print("[atlas] 冷启失败，跳过")
            return
        es = wait_stable(min_elems=8, timeout=12)
        if hub_label:
            for e in es:
                if e["clk"] and hub_label in e["label"]:
                    tap(e["x"], e["y"])
                    break
            es = wait_stable(min_elems=8, timeout=10)
        act = current_focus()[1]
        hub_sig = record(es, act, hub_label or "home")
        print("[atlas] hub sig=%s elems=%d act=%s" % (hub_sig, len(es), act))
        cands = safe_candidates(es, budget)
        print("[atlas] 候选: %s" % " / ".join(c["label"] for c in cands))
        for c in cands:
            print("[atlas] -- 探 «%s» (%d,%d)" % (c["label"], c["x"], c["y"]))
            if not reset_home(pkg):
                continue
            if hub_label:
                for e in wait_stable(min_elems=8, timeout=10):
                    if e["clk"] and hub_label in e["label"]:
                        tap(e["x"], e["y"])
                        break
            tap(c["x"], c["y"])
            time.sleep(3.2)
            es2 = wait_stable(min_elems=5, timeout=10)
            act2 = current_focus()[1]
            s2 = record(es2, act2, c["label"])
            edge(hub_sig, c["label"], c["x"], c["y"], s2)
            print("[atlas]    -> %s (%d elems)" % (s2, len(es2)))

    hub_pass("", max_pages)
    if hub:
        hub_pass(hub, max(3, max_pages - 2))

    ts = time.strftime("%m%d-%H%M%S")
    path = os.path.join(OUT, "%s-%s.json" % (pkg.replace(".", "_"), ts))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=1)
    print("[atlas] pages=%d edges=%d -> %s" % (len(dump["pages"]), len(dump["edges"]), path))


if __name__ == "__main__":
    main()
