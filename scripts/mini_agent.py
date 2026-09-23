#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mini_agent.py — 手机端迷你工头（on-device / Termux）v3

原理（看 → 问 → 做 循环）：
  1. 看：portal /state_full（可访问性树）→ 压缩成元素清单
  2. 问：把"任务 + 屏幕元素"发给决策引擎，拿回"下一步动作"
  3. 做：调用 portal 动作端点（tap/swipe/input_text/key/open_app）执行
  4. 循环直到 done / 步数上限

三种模式（--engine / 环境变量 AGENT_ENGINE）：
  auto（默认）：Jev 起步；"持续无进展"（执行失败/重复动作/动作循环/屏幕卡死/
               低置信度）累计达到阈值时，自动切换 qwen 接管（更慢但更聪明）
  jev ：只走 Jev（最快，不换引擎）
  qwen：只走 qwen（大模型直连，复杂任务 / 手动指定）

依赖：纯标准库（urllib/json/base64）。用法：
  python3 mini_agent.py "任务描述" [--engine auto|jev|qwen] [--max-steps N] [--upgrade-after N]
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request

PORTAL_BASE = os.environ.get("PORTAL_BASE", "http://127.0.0.1:8080")
LLM_BASE = os.environ.get("LLM_BASE", "http://192.168.3.75:8888/v1")
LLM_KEY = os.environ.get("LLM_KEY", "123")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3.8-flash-next")
LLM_THINK = os.environ.get("LLM_THINK", "0") == "1"  # 默认关闭思考链（速度优先）


def _load_secrets():
    """本机密钥（不进 git）：~/bridge/secrets.json = {"portal_token": "...", "jev_key": "..."}"""
    try:
        with open(os.path.expanduser("~/bridge/secrets.json"), encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


_SECRETS = _load_secrets()
PORTAL_TOKEN = os.environ.get("PORTAL_TOKEN") or str(_SECRETS.get("portal_token", ""))
JEV_KEY = os.environ.get("JEV_KEY") or str(_SECRETS.get("jev_key", ""))
JEV_URL = os.environ.get("JEV_URL", "https://api.typesafe.ai/v1/systemone")
OUT_DIR = os.path.expanduser("~/bridge/out")
TRACE_PATH = os.environ.get("TRACE_PATH", "")  # 每任务独立 trace（由控制台注入 ~/bridge/runs/<rid>.trace.jsonl）
SKILLS_DIR = os.path.expanduser("~/bridge/skills")
EXAMPLES_PATH = os.path.join(SKILLS_DIR, "examples.json")

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

SYSTEM_PROMPT = (
    "你是运行在安卓手机里的自动化助手。你会收到当前屏幕上的可访问性元素列表，"
    "每行形如 `(x,y) 文本 (类型) 可点`，括号中的坐标是该元素中心点。\n"
    "你只能输出一个 JSON 对象（不要输出 JSON 以外的任何文字），表示下一步动作：\n"
    '- {"action":"tap","x":数字,"y":数字} 点击坐标\n'
    '- {"action":"swipe","x1":,"y1":,"x2":,"y2":,"duration":500} 滑动\n'
    '- {"action":"input_text","text":"内容"} 在光标处输入文本\n'
    '- {"action":"key","key_code":4} 安卓键码（BACK=4, HOME=3, ENTER=66）\n'
    '- {"action":"open_app","package":"包名"} 打开应用\n'
    '- {"action":"wait"} 等待界面加载\n'
    '- {"action":"done","summary":"给用户的最终答案"} 任务完成时输出\n'
    "规则：一次只做一步；只能使用列表中出现过的坐标；任务完成立即用 done 收尾；"
    '可在 JSON 中加 "thought" 字段简述思路，但不要输出多余文字。'
)


class Portal:
    def __init__(self):
        self.base = PORTAL_BASE.rstrip("/")

    def _req(self, path, method="GET", payload=None, timeout=20, raw=False):
        url = self.base + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + PORTAL_TOKEN)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "")
        if raw:
            return body, ctype
        return json.loads(body)

    @staticmethod
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

    def get_state(self):
        return self._unwrap(self._req("/state_full", timeout=25))

    def screenshot_png(self):
        body, ctype = self._req("/screenshot", raw=True, timeout=25)
        if body[:4] == b"\x89PNG" or "image/" in ctype:
            return body
        d = json.loads(body)
        v = self._unwrap(d)
        if isinstance(v, str):
            return base64.b64decode(v)
        raise RuntimeError("bad screenshot response")

    def tap(self, x, y):
        self._unwrap(self._req("/tap", "POST", {"x": int(x), "y": int(y)}))

    def swipe(self, x1, y1, x2, y2, duration=500):
        self._unwrap(self._req("/swipe", "POST", {
            "startX": int(x1), "startY": int(y1),
            "endX": int(x2), "endY": int(y2), "duration": float(duration)}))

    def input_text(self, text, clear=False):
        b64 = base64.b64encode(text.encode()).decode()
        self._unwrap(self._req("/keyboard/input", "POST", {"base64_text": b64, "clear": clear}))

    def key(self, code):
        self._unwrap(self._req("/keyboard/key", "POST", {"key_code": int(code)}))

    def open_app(self, package):
        self._unwrap(self._req("/app", "POST", {"package": package}))

    def get_apps(self):
        """已安装应用列表 [{packageName, label, ...}]"""
        d = self._unwrap(self._req("/packages", timeout=20))
        return d if isinstance(d, list) else []


def render_tree(state, limit=120):
    """a11y 树 → LLM 友好的元素清单文本"""
    lines = []
    ph = state.get("phone_state") or {}
    lines.append("当前App: %s (%s) 键盘可见: %s" % (
        ph.get("currentApp"), ph.get("packageName"), ph.get("keyboardVisible")))

    def visit(node, depth):
        if len(lines) >= limit + 1 or not isinstance(node, dict):
            return
        text = (node.get("text") or "").strip()
        desc = (node.get("contentDescription") or "").strip()
        label = text if text else desc
        clickable = node.get("isClickable") or node.get("isLongClickable")
        editable = node.get("isEditable")
        b = node.get("boundsInScreen") or {}
        if (label or clickable or editable) and isinstance(b, dict) and b:
            cx = (b.get("left", 0) + b.get("right", 0)) // 2
            cy = (b.get("top", 0) + b.get("bottom", 0)) // 2
            cls = (node.get("className") or "").split(".")[-1]
            flags = []
            if clickable:
                flags.append("可点")
            if editable:
                flags.append("可输入")
            line = "(%d,%d) %s (%s) %s" % (cx, cy, label[:60] or "-", cls, " ".join(flags))
            lines.append(line.rstrip())
        for c in node.get("children") or []:
            visit(c, depth + 1)

    visit(state.get("a11y_tree") or {}, 0)
    if len(lines) > limit + 1:
        lines = lines[: limit + 1] + ["(更多元素已省略)"]
    return "\n".join(lines)


def call_llm(messages, timeout=90):
    payload = {"model": LLM_MODEL, "messages": messages,
               "temperature": 0.2, "max_tokens": 1024}
    if not LLM_THINK:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(LLM_BASE.rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + LLM_KEY)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        d = json.loads(resp.read())
    return d["choices"][0]["message"]["content"]


def parse_action(text):
    t = re.sub(r"<think[^>]*>.*?</think[^>]*>", " ", text, flags=re.S)
    m = re.search(r"\{[^{}]*\}", t, re.S) or re.search(r"\{.*\}", t, re.S)
    if not m:
        return {"action": "wait", "_raw": text[:200]}
    raw = m.group(0)
    for cand in (raw, raw.replace("'", '"')):
        try:
            act = json.loads(cand)
            if isinstance(act, dict) and "action" in act:
                return act
        except Exception:
            pass
    return {"action": "wait", "_raw": text[:200]}


def jev_ask(state, questions, timeout=30):
    payload = {"model": "jev-latest", "state": state, "questions": questions}
    req = urllib.request.Request(JEV_URL, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + JEV_KEY)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def collect_elements(state, limit=110):
    """a11y 树 → [(idx, cx, cy, label, clickable)]"""
    out = []

    def visit(node):
        if len(out) >= limit or not isinstance(node, dict):
            return
        text = (node.get("text") or "").strip()
        desc = (node.get("contentDescription") or "").strip()
        label = text if text else desc
        clickable = bool(node.get("isClickable") or node.get("isLongClickable") or node.get("isEditable"))
        b = node.get("boundsInScreen") or {}
        if label and isinstance(b, dict) and b:
            cx = (b.get("left", 0) + b.get("right", 0)) // 2
            cy = (b.get("top", 0) + b.get("bottom", 0)) // 2
            out.append((len(out), cx, cy, label[:50], clickable))
        for c in node.get("children") or []:
            visit(c)

    visit(state.get("a11y_tree") or {})
    return out


def jev_decide(task, elems, history, experience=None, related_apps=None, cur_pkg=""):
    criteria = {}
    answer_criteria = {}
    for idx, cx, cy, label, clickable in elems:
        criteria["elem_%d" % idx] = "元素%d：%s%s" % (idx, label, "" if clickable else "（仅文字不可点）")
        answer_criteria["elem_%d" % idx] = "元素%d的文本：%s" % (idx, label)
    criteria["scroll_down"] = "目标不在屏幕内，向下滑动"
    criteria["scroll_up"] = "目标不在屏幕内，向上滑动"
    criteria["back"] = "返回上一页"
    criteria["done"] = "任务已完成（屏幕上已能看到所需信息）"
    # 相关应用：允许"直接打开应用"（避免在当前 App 里瞎点）
    if related_apps:
        for i, ra in enumerate(related_apps):
            desc = "打开应用「%s」" % ra.get("label", "")
            if ra.get("package") and ra.get("package") == cur_pkg:
                desc += "（已在此应用中，无需再打开）"
            criteria["open_app_%d" % i] = desc
    answer_criteria["none"] = "答案（如具体数值/结论）尚未出现在屏幕上"
    state = {"task": task, "recent_steps": history[-4:],
             "screen_elements": [{"id": "elem_%d" % i, "text": l} for i, _, _, l, _ in elems]}
    target_instr = ("为完成 `task`，下一步应选哪个动作？答案必须从 `screen_elements` 或"
                    "滑动/返回/完成中选择；若上一步做过同样动作且无效果，不要重复。")
    exp_text = render_experience(experience)
    if exp_text:
        target_instr += "\n参考经验（上次同类任务的成功做法；若与当前屏幕相符，优先参考）：\n" + exp_text
    if related_apps:
        names = "、".join("%s（%s）" % (ra.get("label"), ra.get("package")) for ra in related_apps)
        target_instr += ("\n本机相关应用：%s。若任务需要用某个应用而现在不在其中，"
                         "优先选「打开应用…」而不是在当前应用里乱点。" % names)
    questions = {
        "target": {"type": "choice",
            "instructions": target_instr,
            "criteria": criteria},
        "answer": {"type": "choice",
            "instructions": ("任务要读取的答案（如某个数值、名称、事实）是否已出现在 `screen_elements` 中？"
                              "如果出现，选出包含答案的那个元素；否则选 `none`。"),
            "criteria": answer_criteria},
    }
    resp = jev_ask(state, questions)
    return resp["answers"]


def jev_to_action(ans, elems, related_apps=None):
    ch = (ans or {}).get("choice", "")
    conf = (ans or {}).get("confidence", 0)
    if isinstance(ch, str) and ch.startswith("elem_"):
        try:
            idx = int(ch.split("_", 1)[1])
        except ValueError:
            idx = -1
        for e in elems:
            if e[0] == idx:
                return {"action": "tap", "x": e[1], "y": e[2], "pick": e[3][:30], "confidence": conf}
        return {"action": "wait", "confidence": conf}
    if isinstance(ch, str) and ch.startswith("open_app_"):
        try:
            ai = int(ch.split("open_app_", 1)[1])
        except ValueError:
            ai = -1
        if related_apps and 0 <= ai < len(related_apps):
            ra = related_apps[ai]
            return {"action": "open_app", "package": ra.get("package", ""),
                    "pick": ra.get("label", ""), "confidence": conf}
        return {"action": "wait", "confidence": conf}
    if ch == "scroll_down":
        return {"action": "scroll", "direction": "down", "confidence": conf}
    if ch == "scroll_up":
        return {"action": "scroll", "direction": "up", "confidence": conf}
    if ch == "back":
        return {"action": "key", "key_code": 4, "confidence": conf}
    if ch == "done":
        return {"action": "done", "confidence": conf}
    return {"action": "wait", "confidence": conf}


def qwen_summary(task, screen_text):
    messages = [{"role": "user", "content":
                 "任务：%s\n\n当前屏幕元素：\n%s\n\n请用一句话给出任务要求的答案。" % (task, screen_text[:3000])}]
    return call_llm(messages)


# ---------------------------------------------------------------- 调试 trace
class Tracer:
    """每任务一份 jsonl trace（prompt / reply / action / result），供调试浮窗与复盘。"""

    def __init__(self, path):
        self.path = path
        self.f = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.f = open(path, "a", encoding="utf-8")
        except Exception:
            self.f = None

    def log(self, step, kind, text, **extra):
        if not self.f:
            return
        rec = {"ts": round(time.time(), 2), "step": step, "kind": kind, "text": text}
        rec.update(extra)
        try:
            self.f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.f.flush()
        except Exception:
            pass

    def close(self):
        if self.f:
            try:
                self.f.close()
            except Exception:
                pass
            self.f = None


# ---------------------------------------------------------------- 经验库（外挂 skill / 记忆）
def _bigrams(s):
    s = re.sub(r"\s+", "", s or "")
    if len(s) < 2:
        return {s} if s else set()
    return set(s[i:i + 2] for i in range(len(s) - 1))


def load_experience(task, limit=2, min_score=0.2):
    """从本地经验库检索与当前任务相似的历史成功轨迹（2-gram Jaccard 相似度）。"""
    try:
        with open(EXAMPLES_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    tb = _bigrams(task)
    if not tb:
        return []
    scored = []
    for ex in data:
        eb = _bigrams(ex.get("task", ""))
        if not eb:
            continue
        score = len(tb & eb) / float(len(tb | eb))
        if score >= min_score:
            scored.append((score, ex))
    scored.sort(key=lambda x: -x[0])
    return [ex for _, ex in scored[:limit]]


def save_experience(task, result, steps, engine):
    """任务成功后保存轨迹（按任务文本去重置顶，上限 50 条）。"""
    if not task or not steps:
        return
    try:
        os.makedirs(SKILLS_DIR, exist_ok=True)
        try:
            with open(EXAMPLES_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
        if not isinstance(data, list):
            data = []
        data = [d for d in data if d.get("task") != task]
        data.insert(0, {"task": task, "result": (result or "")[:200], "engine": engine,
                        "steps": steps[-20:], "ts": int(time.time())})
        with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
            json.dump(data[:50], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def render_experience(exps):
    """经验列表 → 可注入 prompt 的文本。"""
    if not exps:
        return ""
    lines = []
    for i, ex in enumerate(exps, 1):
        lines.append("%d) 上次「%s」的做法（%d 步，结果：%s）：" % (
            i, ex.get("task", "")[:36], len(ex.get("steps") or []), (ex.get("result") or "")[:40]))
        for s in (ex.get("steps") or [])[:12]:
            lines.append("   %s" % s)
    return "\n".join(lines)


def action_to_line(act):
    """动作 → 人可读单行（经验库 / 调试窗共用）。"""
    a = act.get("action")
    if a == "tap":
        extra = ("→%s" % act.get("pick")) if act.get("pick") else ""
        return "tap(%s,%s)%s" % (act.get("x"), act.get("y"), extra)
    if a == "scroll":
        return "scroll_%s" % (act.get("direction") or "down")
    if a == "swipe":
        return "swipe(%s,%s→%s,%s)" % (act.get("x1"), act.get("y1"), act.get("x2"), act.get("y2"))
    if a == "input_text":
        return "input_text(%s)" % (act.get("text", "")[:30])
    if a == "key":
        return "key(%s)" % act.get("key_code")
    if a == "open_app":
        return "open_app(%s)" % act.get("package")
    if a in ("done", "wait"):
        return a
    return str(a)


# ---------------------------------------------------------------- 应用名解析（治"包名幻觉"）
def resolve_package(want, apps):
    """把模型给出的包名解析成本机真实包名（精确 → 关键词模糊）。
    例：com.miui.weather → com.coloros.weather2（本机天气 App）。
    返回 None 表示本机明确没有匹配的应用。
    """
    if not want:
        return None
    if not apps:
        return want   # 没有列表时不做矫正（沿用旧行为）
    w = str(want).strip().lower()
    for a in apps:
        p = str(a.get("packageName") or "")
        if p and p.lower() == w:
            return p                       # 精确命中
    key = w.split(".")[-1]
    if len(key) >= 3:
        cands = []
        for a in apps:
            p = str(a.get("packageName") or "")
            if p and key in p.lower():
                cands.append((len(p), p))  # 更短的包名更像主 App
        if cands:
            cands.sort()
            return cands[0][1]
    return None


def match_apps_for_task(task, apps, limit=3):
    """从任务文本里找相关应用（label 子串匹配；同 label 保留包名最短的，更可能是主 App）。"""
    t = re.sub(r"\s+", "", task or "").lower()
    hits = []
    for a in apps:
        label = str(a.get("label") or "").strip()
        pkg = str(a.get("packageName") or "")
        if not label or not pkg:
            continue
        lab = re.sub(r"\s+", "", label).lower()
        if len(lab) >= 2 and lab in t:
            hits.append((len(lab), len(pkg), label, pkg))
    hits.sort(key=lambda x: (-x[0], x[1]))
    out, seen_pkg, seen_label = [], set(), set()
    for _, _, label, pkg in hits:
        if pkg in seen_pkg or label in seen_label:
            continue
        seen_pkg.add(pkg)
        seen_label.add(label)
        out.append({"label": label, "package": pkg})
        if len(out) >= limit:
            break
    return out


class Progress:
    """连续无进展检测器（纯逻辑，可单测）。

    每步喂入 (动作, ok, 屏幕指纹)，累计"无进展分"：
      - 执行失败                +1
      - 重复上一动作 / 动作循环   +1（两者只记一次）
      - 屏幕连续 3 步无变化       +1
      - Jev 置信度连续 2 步 <0.35 +1
    有进展（ok 且屏幕有变化、无 flag）时 -1（缓慢回血）。
    """

    def __init__(self, window=6):
        self.window_size = window
        self.sig_window = []
        self.prev_sig = None
        self.screen_prev = None
        self.screen_stag = 0
        self.low_conf_run = 0
        self.score = 0

    @staticmethod
    def sig_of(act):
        a = act.get("action")
        if a in (None, "wait", "done", "scroll", "swipe"):
            return None  # 探索类动作不参与"重复"判定
        if a == "tap":
            return ("tap", int(act.get("x", 0)) // 8, int(act.get("y", 0)) // 8)
        if a == "key":
            return ("key", act.get("key_code"))
        if a == "input_text":
            return ("input_text", str(act.get("text", ""))[:24])
        if a == "open_app":
            return ("open_app", str(act.get("package", "")))
        return (a,)

    def note(self, act, ok, screen_hash):
        """返回本步命中的 flags 列表"""
        flags = []
        add = 0
        screen_changed = (screen_hash != self.screen_prev)
        sig = self.sig_of(act)
        if not ok:
            add += 1
            flags.append("执行失败")
        if sig is not None:
            if sig == self.prev_sig:
                add += 1
                flags.append("重复动作")
            elif sig in self.sig_window:
                add += 1
                flags.append("动作循环")
            self.prev_sig = sig
            self.sig_window.append(sig)
            self.sig_window = self.sig_window[-self.window_size:]
        else:
            self.prev_sig = None
        if screen_hash == self.screen_prev:
            self.screen_stag += 1
        else:
            self.screen_stag = 0
        self.screen_prev = screen_hash
        if self.screen_stag >= 3:
            add += 1
            flags.append("屏幕无变化")
            self.screen_stag = 0
        conf = act.get("confidence")
        if isinstance(conf, (int, float)) and 0 < conf < 0.35:
            self.low_conf_run += 1
            if self.low_conf_run >= 2:
                add += 1
                flags.append("低置信度")
                self.low_conf_run = 0
        else:
            self.low_conf_run = 0
        self.score += add
        if add == 0 and ok and screen_changed:
            self.score = max(0, self.score - 1)  # 有进展缓慢回血
        return flags


def decide(step, task, state, history, engine_now, elems, experience=None, related_apps=None):
    """返回 (act, engine_name, seconds, trace_info)。trace_info = {"prompt":..., "reply":...}"""
    t0 = time.time()
    if engine_now == "jev":
        try:
            cur_pkg = ""
            try:
                cur_pkg = (state.get("phone_state") or {}).get("packageName") or ""
            except Exception:
                pass
            answers = jev_decide(task, elems, history, experience, related_apps, cur_pkg)
            act = jev_to_action(answers.get("target"), elems, related_apps)
            ans_pick = (answers.get("answer") or {}).get("choice", "none")
            if isinstance(ans_pick, str) and ans_pick.startswith("elem_"):
                try:
                    aidx = int(ans_pick.split("_", 1)[1])
                except ValueError:
                    aidx = -1
                for e in elems:
                    if e[0] == aidx:
                        act["answer_text"] = e[3]
                        break
            tips = "任务: %s | 屏幕元素 %d 个 | 最近步骤: %s" % (
                task, len(elems), json.dumps(history[-2:], ensure_ascii=False)[:200])
            if experience:
                tips += "\n[已注入经验 %d 条]" % len(experience)
            ti = {"prompt": tips, "reply": json.dumps(answers, ensure_ascii=False)[:1200]}
            return act, "jev", time.time() - t0, ti
        except Exception as e:
            print("[step %d] jev failed: %r -> qwen fallback" % (step, e))
    screen = render_tree(state)
    exp_text = render_experience(experience)
    exp_block = ("\n\n参考经验（上次类似任务的成功做法，可借鉴；若与实际屏幕不符则忽略）：\n" + exp_text) \
        if exp_text else ""
    app_hint = ""
    if related_apps:
        app_hint = "\n\n本机可用应用：" + "、".join(
            "%s(%s)" % (ra.get("label"), ra.get("package")) for ra in related_apps) + \
            "。如需打开应用请严格使用以上包名（不要臆造别的包名）。"
    user = ("任务: %s\n\n第 %d 步。当前屏幕元素清单：\n%s%s%s\n\n"
            "请输出下一步动作 JSON。" % (task, step, screen, exp_block, app_hint))
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-10:] + \
               [{"role": "user", "content": user}]
    reply = call_llm(messages)
    return parse_action(reply), "qwen", time.time() - t0, {"prompt": user, "reply": reply}


def parse_args():
    argv = sys.argv[1:]
    kv = {}
    positional = []
    flags = {"--max-steps", "--engine", "--upgrade-after"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in flags and i + 1 < len(argv):
            kv[a] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--"):
            i += 1
            continue
        positional.append(a)
        i += 1
    task = positional[0] if positional else "打开设置，告诉我电池电量百分比（数字和充电状态）"
    mode = (kv.get("--engine") or os.environ.get("AGENT_ENGINE") or "auto").lower()
    if mode not in ("auto", "jev", "qwen"):
        mode = "auto"
    try:
        max_steps = int(kv.get("--max-steps") or os.environ.get("MAX_STEPS", "25"))
    except ValueError:
        max_steps = 25
    try:
        upgrade_after = int(kv.get("--upgrade-after") or os.environ.get("UPGRADE_AFTER", "3"))
    except ValueError:
        upgrade_after = 3
    return task, max_steps, mode, upgrade_after


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    task, max_steps, mode, upgrade_after = parse_args()

    portal = Portal()
    history = []
    trace_path = TRACE_PATH or os.path.join(OUT_DIR, "agent_trace.jsonl")
    tracer = Tracer(trace_path)
    usage = {"jev": 0, "qwen": 0}
    engine_now = "qwen" if mode == "qwen" else "jev"
    prog = Progress()
    aborted = False
    exec_log = []
    fail_counts = {}   # 动作签名 -> 连续失败次数（>=2 硬阻断）

    print("[agent] task: %s" % task)
    print("[agent] mode: %s | start engine: %s | upgrade-after: %d | max-steps: %d" %
          (mode, engine_now, upgrade_after, max_steps))
    print("[agent] LLM: %s model=%s" % (LLM_BASE, LLM_MODEL))
    print("[agent] trace: %s" % trace_path)
    experience = load_experience(task)
    if experience:
        print("[agent] 已注入历史经验 %d 条（源自 ~/bridge/skills/examples.json）" % len(experience))
    apps = []
    try:
        apps = portal.get_apps()
        print("[agent] 应用列表: %d 个已安装应用" % len(apps))
    except Exception as e:
        print("[agent] 应用列表加载失败（跳过包名矫正）: %r" % (e,))
    related_apps = match_apps_for_task(task, apps)
    if related_apps:
        print("[agent] 任务相关应用: %s" % "、".join(
            "%s(%s)" % (ra["label"], ra["package"]) for ra in related_apps))

    for step in range(1, max_steps + 1):
        t_step = time.time()
        state = None
        for attempt in range(3):
            try:
                state = portal.get_state()
                break
            except Exception as e:
                print("[step %d] portal state error (%d/3): %r" % (step, attempt + 1, e))
                time.sleep(1.5)
        if state is None:
            print("[agent] portal 连续取状态失败（窗口切换/系统弹窗？），中止。")
            aborted = True
            break
        elems = collect_elements(state)
        screen_hash = hash(tuple((e[3][:24], e[1] // 16, e[2] // 16) for e in elems))
        try:
            act, eng, dec_dt, ti = decide(step, task, state, history, engine_now, elems,
                                          experience, related_apps)
        except Exception as e:
            print("[step %d] decide error: %r" % (step, e))
            time.sleep(2)
            continue
        usage[eng] = usage.get(eng, 0) + 1
        print("[step %d] %s %.1fs -> %s" % (step, eng, dec_dt, json.dumps(act, ensure_ascii=False)[:220]))
        if ti:
            tracer.log(step, "prompt", ti.get("prompt", ""), engine=eng)
            tracer.log(step, "reply", ti.get("reply", ""), engine=eng)
        tracer.log(step, "action", action_to_line(act), engine=eng,
                   confidence=act.get("confidence"), raw=json.dumps(act, ensure_ascii=False))

        a = act.get("action")
        ok = True
        exec_err = ""
        if a == "done":
            summary = act.get("summary", "")
            if not summary and act.get("answer_text"):
                summary = act["answer_text"]
            if not summary and engine_now != "qwen":
                try:
                    summary = qwen_summary(task, render_tree(state))
                except Exception as e:
                    summary = "(总结生成失败: %r)" % e
            print("[agent] engine-usage: jev=%d qwen=%d" % (usage["jev"], usage["qwen"]))
            print("[agent] DONE: %s" % summary)
            tracer.log(step, "done", summary)
            tracer.close()
            if exec_log:
                save_experience(task, summary, exec_log, mode)
                print("[agent] 经验已保存: %d 步 → ~/bridge/skills/examples.json" % len(exec_log))
            return 0

        # —— 重复失败动作硬阻断（同一动作连续失败 ≥2 次 → 拒绝执行，逼模型换策略） ——
        sig = Progress.sig_of(act)
        blocked = sig is not None and fail_counts.get(sig, 0) >= 2
        if blocked:
            ok = False
            exec_err = "该动作已连续失败多次（很可能无效/目标不存在）"
            print("[step %d] BLOCK 重复失败动作: %s" % (step, sig))
        else:
            try:
                if a == "tap":
                    portal.tap(act["x"], act["y"])
                elif a == "swipe":
                    portal.swipe(act.get("x1", 0), act.get("y1", 0), act.get("x2", 0),
                                 act.get("y2", 0), act.get("duration", 500))
                elif a == "scroll":
                    if (act.get("direction") or "down").lower() == "up":
                        portal.swipe(540, 700, 540, 1700, 500)
                    else:
                        portal.swipe(540, 1700, 540, 700, 500)
                elif a == "input_text":
                    portal.input_text(act.get("text", ""), act.get("clear", False))
                elif a == "key":
                    portal.key(act.get("key_code", 4))
                elif a == "open_app":
                    want = act.get("package", "")
                    real = resolve_package(want, apps)
                    if apps and real is None:
                        ok = False
                        exec_err = "本机未找到应用「%s」（已核对全部已安装应用）" % want
                        print("[step %d] open_app 解析失败: %s" % (step, want))
                    else:
                        if real and real != want:
                            print("[step %d] open_app 包名矫正: %s -> %s" % (step, want, real))
                            tracer.log(step, "result", "包名矫正: %s -> %s" % (want, real))
                            act["package"] = real
                        portal.open_app(real or want)
                elif a == "wait":
                    time.sleep(act.get("seconds", 1.5))
                else:
                    ok = False
                    exec_err = "未知动作类型"
                    print("[step %d] unknown action: %r" % (step, a))
            except Exception as e:
                ok = False
                exec_err = str(e)[:180]
                print("[step %d] exec error: %r" % (step, e))
        if sig is not None:
            if ok:
                fail_counts[sig] = 0
            else:
                fail_counts[sig] = fail_counts.get(sig, 0) + 1

        tracer.log(step, "result", ("ok: " if ok else "FAIL: ") + action_to_line(act),
                   ok=ok, ms=int((time.time() - t_step) * 1000), blocked=blocked)
        exec_log.append(action_to_line(act) + ("" if ok else "（失败）"))
        history.append({"role": "assistant", "content": json.dumps(act, ensure_ascii=False)})
        if blocked:
            extra = ""
            if related_apps and a == "open_app":
                extra = " 本机可用的相关应用：" + "、".join(
                    "%s(%s)" % (ra["label"], ra["package"]) for ra in related_apps) + "。"
            history.append({"role": "user", "content":
                            "上一步没有执行：动作 %s 已连续失败多次（很可能无效/目标不存在）。"
                            "请换一种完全不同的做法（换应用/换入口/用搜索），不要重复同一动作。%s"
                            % (json.dumps(act, ensure_ascii=False)[:140], extra)})
        else:
            history.append({"role": "user", "content":
                            "上一步动作执行%s%s。" % ("成功" if ok else "失败",
                                                      ("：" + exec_err) if (not ok and exec_err) else "")})

        flags = prog.note(act, ok, screen_hash)
        if flags:
            print("[step %d] signals: %s (无进展 x%d/%d)" %
                  (step, ",".join(flags), prog.score, upgrade_after))

        if mode == "auto" and engine_now == "jev" and prog.score >= upgrade_after:
            print("[switch] 连续无进展 x%d（%s）→ qwen 接管（从第 %d 步起）" %
                  (prog.score, ",".join(flags) if flags else "-", step + 1))
            engine_now = "qwen"
            prog.score = 0
            history.append({"role": "user", "content":
                            "快速引擎连续多步无进展（重复动作/屏幕无变化）。现在由更强的模型接管："
                            "请根据当前屏幕与任务重新规划，避免重复此前无效动作。"})
        time.sleep(0.8)

    print("[agent] engine-usage: jev=%d qwen=%d" % (usage["jev"], usage["qwen"]))
    if aborted:
        print("[agent] FAILED: portal unreachable (aborted).")
    else:
        print("[agent] max steps (%d) reached, no done." % max_steps)
    tracer.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
