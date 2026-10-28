#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-
"""store.py —「数据仓」（P0）：任务结果的结构化落库（仅标准库）。

三张表：
  sessions  一次任务 = 一个会话（rid 与 runs/<rid> 同名）
  messages  会话里的对话（用户任务 / 助手结果）
  datasets  从结果里抽出的结构化数据（编号列表 → 行）

由 mini_console.py（root 常驻）调用；库文件：~/bridge/store.db
"""
import json
import os
import re
import sqlite3
import time

HOME = os.path.expanduser("~")
DB_PATH = os.path.join(HOME, "bridge", "store.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  rid TEXT PRIMARY KEY, task TEXT NOT NULL,
  mode TEXT, exec_mode TEXT DEFAULT 'test', rec TEXT,
  engine TEXT, state TEXT,
  started REAL, ended REAL, usage TEXT,
  result TEXT, failed_reason TEXT,
  topic TEXT, created REAL);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rid TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, ts REAL);
CREATE TABLE IF NOT EXISTS datasets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rid TEXT NOT NULL, topic TEXT, kind TEXT, title TEXT,
  columns TEXT, rows TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS ix_msg_rid ON messages(rid);
CREATE INDEX IF NOT EXISTS ix_ds_rid ON datasets(rid);
CREATE INDEX IF NOT EXISTS ix_ds_topic ON datasets(topic);
CREATE INDEX IF NOT EXISTS ix_sess_started ON sessions(started);
"""

_NUM_ITEM = re.compile(r"(?:^|[\s；;：:，,\n])[（(]?(\d{1,2})[）)]?\s*[\.、．:：]\s*([^；;：:\n]+)")


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=6)
    c.row_factory = sqlite3.Row
    return c


def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)
        try:
            c.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass


def start_session(rid, task, mode="auto", exec_mode="test", rec=None, started=None):
    """任务开工：建会话 + 写第一条用户消息（幂等）。"""
    init()
    now = time.time()
    started = started or now
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions(rid,task,mode,exec_mode,rec,state,started,created) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(rid) DO UPDATE SET task=excluded.task, mode=excluded.mode, "
            "exec_mode=excluded.exec_mode, rec=COALESCE(excluded.rec, sessions.rec), "
            "state=excluded.state, started=excluded.started",
            (rid, task, mode or "auto", exec_mode or "test", rec, "running", started, now))
    add_message(rid, "user", task, ts=started)


def add_message(rid, role, text, ts=None):
    if not text:
        return
    with _conn() as c:
        c.execute("INSERT INTO messages(rid,role,text,ts) VALUES(?,?,?,?)",
                  (rid, role, text, ts or time.time()))


def finish_session(rid, state, engine=None, usage=None, result=None, failed_reason=None,
                   ended=None, rec=None):
    """任务收工：更新会话 + 助手消息 + 结构化数据集（幂等：重复调用会重复写消息，调用方保证一次）。"""
    init()
    ended = ended or time.time()
    row = None
    with _conn() as c:
        row = c.execute("SELECT task, started FROM sessions WHERE rid=?", (rid,)).fetchone()
        c.execute("UPDATE sessions SET state=?, engine=?, usage=?, result=?, failed_reason=?, ended=? "
                  "WHERE rid=?",
                  (state, engine, usage, result, failed_reason, ended, rid))
        if rec is not None:
            c.execute("UPDATE sessions SET rec=? WHERE rid=?", (rec, rid))
    task = (row["task"] if row else "") or ""
    txt = (result or "").strip() or ("任务未完成：" + (failed_reason or "未知原因"))
    add_message(rid, "assistant", txt, ts=ended)
    if (result or "").strip():
        try:
            ingest_result(rid, task, result, ts=ended)
        except Exception:
            pass


_NUM_ITEM = re.compile(
    r"(?:^|[\s；;:：，,\n])[（(]?(\d{1,2})[）)]?\s*[\.、．:：\)]\s*([^；;：:\n]+)")
_NUM_ITEM2 = re.compile(
    r"(?:^|[\s；;:：，,\n])第\s*(\d{1,2})\s*[条名位个]\s*[:：、.．]?\s*([^；;：:\n]+)")
# 只匹配「编号标记」本身（不含内容）—— 按标记位置切段才不会把相邻两项吞成一项
# 注意：前置字符类必须含全角冒号「：」，否则「前三条是：1. 甲」第一条会漏
_MARK = re.compile(
    r"(?:^|[\s；;:：，,\n])(?:[（(]?(\d{1,2})\s*(?:[）)]|[\.、．:：\)])\s*"
    r"|第\s*(\d{1,2})\s*[条名位个]\s*[:：、.．]?)\s*")
_DASH_ITEM = re.compile(r"(?:^|\n)\s*[-·•*]\s+([^\n；;]+)")
_FACT_ITEM = re.compile(r"第\s*(\d{1,2})\s*[条名位个]\s*是\s*[:：]?\s*([^\n；;]+)")
_PLAIN_SPLIT = re.compile(r"\s*[/／、|｜]\s*")


def parse_list_items(text):
    """从答案文本里抽编号列表 → [item, ...] 或 None。

    2026-10-28 放宽。原规则要求「≥3 项且从 1 连续」，端侧实测（store.db：
    sessions=10 / datasets=0）证明它把真实答案几乎全挡在门外 ——
    「热搜前 2 条」「前 3 个应用」这类任务根本落不进数据仓。
    现在：≥2 项即认，按出现顺序（允许不连续），并补 6 种常见写法
    （`1.` / `1、` / `1)` / `（1）` / `第1条` / `- 无序`）。

    实现要点：先只找「编号标记」的位置，再按标记切段取内容。
    老写法用贪婪内容正则（`[^；;：:\n]+`）会把「1、甲 2）乙」整条吞成一项。
    """
    if not text:
        return None
    out = []
    marks = list(_MARK.finditer(text))
    if len(marks) >= 2:
        for i, m in enumerate(marks):
            start = m.end()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            t = text[start:end].strip().strip("。．. ；;，, ")
            if t.startswith("是"):          # 「第N条是X」→ 别把"是："吃进内容
                t = t.lstrip("是").lstrip("：: ")
            if t:
                out.append(t)
    if not out:
        for m in _DASH_ITEM.finditer(text):
            t = m.group(1).strip().strip("。．.  ")
            if t:
                out.append(t)
    if not out:
        # 没有编号、但用「/」「、」「|」并列的答案（实测「读前 3 个应用名」
        # 的典型输出就是「哔哩哔哩 / 酷安 / OneNote」）—— 保守认定：
        # ≥3 段、每段 ≤24 字、整段没有句号，才当列表；否则一律不认。
        t0 = (text or "").strip()
        if t0 and len(t0) <= 120 and "。" not in t0:
            parts = [p.strip() for p in _PLAIN_SPLIT.split(t0) if p.strip()]
            if 3 <= len(parts) <= 12 and all(len(p) <= 24 for p in parts):
                out = parts
    dedup, res = set(), []
    for t in out:
        if t not in dedup:
            dedup.add(t)
            res.append(t)
    return res if len(res) >= 2 else None


def parse_single_fact(text):
    """「第 N 条 / 第 N 名 是 X」这类单值答案 → (标签, 值) 或 None。"""
    if not text:
        return None
    m = _FACT_ITEM.search(text)
    if not m:
        return None
    v = m.group(2).strip().strip("。．. ")
    return ("第%s条" % m.group(1), v) if v else None


def ingest_result(rid, task, result, ts=None):
    """把一次任务的结果落成结构化数据（列表 或 单值）。返回写入条数。

    2026-10-28 新增。这是「跨 App 汇总」的前提：前一个 App 采集到的东西必须
    先变成结构化的一行一行，后面的环节才有东西可消费 —— 而不是只活在最后那句答案里。
    """
    txt = (result or "").strip()
    if not txt or not rid:
        return 0
    init()
    n = 0
    items = parse_list_items(txt)
    if items:
        title = _list_title(txt) or ((task or "")[:22] or "列表")
        add_dataset(rid, topic=task or None, kind="list", title=title,
                    columns=["序号", "内容"],
                    rows=[[i + 1, t] for i, t in enumerate(items)], ts=ts)
        return 1
    f = parse_single_fact(txt)
    if f:
        add_dataset(rid, topic=task or None, kind="fact", title=f[0],
                    columns=["项", "值"], rows=[[f[0], f[1]]], ts=ts)
        return 1
    return n


def _list_title(text):
    m = _NUM_ITEM.search(text)
    if not m:
        return None
    head = text[:m.start()].strip().rstrip("：:，,；; ")
    return head[-26:] if head else None


def add_dataset(rid, topic=None, kind="list", title=None, columns=None, rows=None, ts=None):
    with _conn() as c:
        c.execute("INSERT INTO datasets(rid,topic,kind,title,columns,rows,ts) VALUES(?,?,?,?,?,?,?)",
                  (rid, topic, kind, title,
                   json.dumps(columns or [], ensure_ascii=False),
                   json.dumps(rows or [], ensure_ascii=False), ts or time.time()))


def list_sessions(limit=50, q=None, offset=0):
    init()
    sql = ("SELECT rid,task,mode,exec_mode,engine,state,started,ended,usage,"
           "result,failed_reason,rec FROM sessions")
    args = []
    if q:
        sql += " WHERE task LIKE ? OR result LIKE ?"
        args += ["%" + q + "%", "%" + q + "%"]
    sql += " ORDER BY started DESC LIMIT ? OFFSET ?"
    args += [int(limit), int(offset)]
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args)]


def count_sessions(q=None):
    """会话总数（前端分页「还有 N 条」用）。"""
    init()
    sql = "SELECT COUNT(*) AS n FROM sessions"
    args = []
    if q:
        sql += " WHERE task LIKE ? OR result LIKE ?"
        args += ["%" + q + "%", "%" + q + "%"]
    with _conn() as c:
        row = c.execute(sql, args).fetchone()
    return int(row["n"]) if row else 0


def _ds_out(r):
    d = dict(r)
    d["columns"] = json.loads(d.get("columns") or "[]")
    d["rows"] = json.loads(d.get("rows") or "[]")
    return d


def get_session(rid):
    init()
    with _conn() as c:
        s = c.execute("SELECT * FROM sessions WHERE rid=?", (rid,)).fetchone()
        if not s:
            return None
        msgs = [dict(r) for r in c.execute(
            "SELECT role,text,ts FROM messages WHERE rid=? ORDER BY id", (rid,))]
        dss = [_ds_out(r) for r in c.execute(
            "SELECT * FROM datasets WHERE rid=? ORDER BY id", (rid,))]
        same = []
        if s["task"]:
            rows = c.execute(
                "SELECT d.rid, d.rows, d.ts, s2.started FROM datasets d "
                "LEFT JOIN sessions s2 ON s2.rid=d.rid "
                "WHERE d.topic=? AND d.rid<>? ORDER BY d.ts DESC LIMIT 9", (s["task"], rid)).fetchall()
            for r in rows:
                try:
                    n = len(json.loads(r["rows"] or "[]"))
                except Exception:
                    n = 0
                same.append({"rid": r["rid"], "started": r["started"], "count": n})
    return {"session": dict(s), "messages": msgs, "datasets": dss, "same_topic": same}


def import_runs(runs_dir, limit=120):
    """把 runs/*.json 老记录回填进库（幂等：rid 已存在则跳过）。返回新导入条数。"""
    init()
    try:
        names = sorted(n for n in os.listdir(runs_dir)
                       if n.endswith(".json") and not n.startswith("_"))
    except Exception:
        return 0
    n = 0
    for name in names[-limit:]:
        rid = name[:-5]
        with _conn() as c:
            if c.execute("SELECT 1 FROM sessions WHERE rid=?", (rid,)).fetchone():
                continue
        try:
            with open(os.path.join(runs_dir, name), encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        st = meta.get("state") or "failed"
        if st == "running":
            st = "failed"
        try:
            start_session(rid, meta.get("task") or "(无任务)", meta.get("mode"),
                          exec_mode=meta.get("exec_mode") or "test",
                          started=meta.get("started"))
            finish_session(rid, st, engine=meta.get("engine"), usage=meta.get("usage"),
                           result=meta.get("result"), failed_reason=meta.get("failed_reason"),
                           ended=meta.get("ended"), rec=meta.get("rec"))
            n += 1
        except Exception:
            continue
    return n


def _selftest():
    """纯解析函数自测（不碰数据库，PC 上可直接跑）。"""
    fails = []

    def chk(name, cond):
        print("  %-34s %s" % (name, "PASS" if cond else "FAIL"))
        if not cond:
            fails.append(name)

    chk("列表 老格式 3 项", len(parse_list_items("1. 甲\n2. 乙\n3. 丙") or []) == 3)
    chk("列表 2 项也认（2026-10-28 放宽）", len(parse_list_items("1. 甲\n2. 乙") or []) == 2)
    chk("列表 顿号/括号写法", len(parse_list_items("1、甲 2）乙") or []) == 2)
    chk("列表 第N条写法", len(parse_list_items("第1条：甲；第2条：乙") or []) == 2)
    chk("列表 无序 - 写法", len(parse_list_items("- 甲\n- 乙") or []) == 2)
    chk("单条 第N条 不误判成列表", parse_list_items("第 3 条是：丙") is None)
    _f = parse_single_fact("第 10 条是：Doinb回应al零胜十六强") or ("", "")
    chk("单值 第N条是X", _f[1].startswith("Doinb"))
    chk("纯叙述 → 不落库", parse_list_items("今天天气不错，没什么可列的。") is None)
    print("全部通过" if not fails else "有 %d 项失败" % len(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())

