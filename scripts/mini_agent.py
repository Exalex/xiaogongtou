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
FAILURES_PATH = os.path.join(SKILLS_DIR, "failures.json")

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
    "done 的 summary 必须包含实际查到的具体内容（如新闻标题/名称/数值），"
    "不要只说「已找到/包含多条」等空话；"
    "搜索/输入类任务：先 tap 点击搜索框或输入框，等键盘弹出后用 input_text 输入关键词，"
    "再按 ENTER(key_code 66) 或点击「搜索」按钮提交，最后读取搜索结果；"
    "禁止操作登录/验证码/账号密码类元素（不要点击、不要输入）；"
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
        try:
            self._unwrap(self._req("/tap", "POST", {"x": int(x), "y": int(y)}))
        except Exception as e:
            r = bridge_cmd("tap %d %d" % (int(x), int(y)))
            if not r.startswith("ok"):
                raise RuntimeError("tap 双通道失败: %r / %s" % (e, r))
            print("[portal] tap 经 root 桥完成 (%s,%s)" % (x, y))

    def swipe(self, x1, y1, x2, y2, duration=500):
        try:
            self._unwrap(self._req("/swipe", "POST", {
                "startX": int(x1), "startY": int(y1),
                "endX": int(x2), "endY": int(y2), "duration": float(duration)}))
        except Exception as e:
            r = bridge_cmd("swipe %d %d %d %d %d" % (int(x1), int(y1), int(x2), int(y2), int(duration)))
            if not r.startswith("ok"):
                raise RuntimeError("swipe 双通道失败: %r / %s" % (e, r))
            print("[portal] swipe 经 root 桥完成")

    def input_text(self, text, clear=False):
        b64 = base64.b64encode(text.encode()).decode()
        self._unwrap(self._req("/keyboard/input", "POST", {"base64_text": b64, "clear": clear}))

    def key(self, code):
        try:
            self._unwrap(self._req("/keyboard/key", "POST", {"key_code": int(code)}))
        except Exception as e:
            r = bridge_cmd("key %d" % int(code))
            if not r.startswith("ok"):
                raise RuntimeError("key 双通道失败: %r / %s" % (e, r))
            print("[portal] key 经 root 桥完成")

    def open_app(self, package):
        try:
            self._unwrap(self._req("/app", "POST", {"package": package}))
        except Exception as e:
            r = bridge_cmd("open %s" % package)
            if not r.startswith("ok"):
                raise RuntimeError("open_app 双通道失败: %r / %s" % (e, r))
            print("[portal] open_app 经 root 桥完成: %s" % package)

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
            out.append((len(out), cx, cy, label[:200], clickable))
        for c in node.get("children") or []:
            visit(c)

    visit(state.get("a11y_tree") or {})
    return out


def render_elems(elems):
    """补充后的元素清单（portal + 桥树）→ LLM 友好文本（qwen 与 jev 共用同一"事实来源"，
    修复：此前 qwen 只吃 portal 原始树，桥树补盲对它不可见）。"""
    lines = []
    for idx, x, y, label, clickable in elems:
        lines.append("(%d,%d) %s%s" % (x, y, label, " 可点" if clickable else ""))
    return "\n".join(lines)


def parse_uiauto_xml(xml):
    """uiautomator dump XML → [(idx, cx, cy, label, clickable)]"""
    import xml.etree.ElementTree as ET
    if not xml:
        return []
    cut = xml.find("<hierarchy")
    if cut > 0:
        xml = xml[cut:]
    try:
        root = ET.fromstring(xml)
    except Exception:
        try:
            root = ET.fromstring(xml[:xml.rindex("</hierarchy>") + len("</hierarchy>")])
        except Exception:
            return []
    out = []

    def visit(n):
        t = (n.get("text") or "").strip()
        d = (n.get("content-desc") or "").strip()
        label = t if t else d
        clickable = (n.get("clickable") == "true") or (n.get("long-clickable") == "true")
        m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", n.get("bounds") or "")
        if label and m:
            cx = (int(m.group(1)) + int(m.group(3))) // 2
            cy = (int(m.group(2)) + int(m.group(4))) // 2
            out.append((len(out), cx, cy, label[:200], clickable))
        for c in n:
            visit(c)

    visit(root)
    return out


def uiauto_elements(timeout=8.0):
    """经 root 桥（uidump-bridge.sh）取 uiautomator 完整树；失败返回 []。
    用途：portal 的 a11y 树会过滤"不重要"视图（如微博信息流），此处补盲。"""
    req = os.path.expanduser("~/bridge/.uidump_req")
    out = os.path.expanduser("~/bridge/.uidump.xml")
    try:
        try:
            os.remove(out)
        except OSError:
            pass
        with open(req, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if os.path.getsize(out) > 100:
                    break
            except OSError:
                pass
            time.sleep(0.15)
        with open(out, encoding="utf-8", errors="replace") as f:
            elems = parse_uiauto_xml(f.read())
        # 限流：uiautomator 树可能几百个元素（Jev criteria 上限 255 / prompt 也会爆炸）
        # 保留：可点元素优先（最多 80）+ 有意义的文本元素（最多 40），重新编号
        clicks = [e for e in elems if e[4]][:80]
        texts = [e for e in elems if not e[4] and len(e[3]) >= 2][:40]
        merged = clicks + texts
        return [(i, e[1], e[2], e[3], e[4]) for i, e in enumerate(merged)]
    except Exception as e:
        print("[agent] uiauto 补盲失败: %r" % (e,))
        return []


def jev_decide(task, elems, history, experience=None, related_apps=None, cur_pkg="", plan=None):
    # 保护：Jev 的 Choice criteria 选项上限 255（含动作项）——元素过多时截断
    if len(elems) > 180:
        elems = elems[:180]
    criteria = {}
    answer_criteria = {}
    for idx, cx, cy, label, clickable in elems:
        criteria["elem_%d" % idx] = "元素%d：%s%s" % (idx, label, "" if clickable else "（仅文字不可点）")
        answer_criteria["elem_%d" % idx] = "元素%d的文本：%s" % (idx, label)
    criteria["scroll_down"] = "目标不在屏幕内，向下滑动"
    criteria["scroll_up"] = "目标不在屏幕内，向上滑动"
    criteria["back"] = "返回上一页"
    criteria["wait"] = "页面正在加载/刚要切换，先等一等（仅加载场景）"
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
                    "滑动/返回/完成中选择；若上一步做过同样动作且无效果，不要重复。"
                    "不要选择「登录/验证码/获取验证码/密码」类元素（系统安全规则禁止）。")
    exp_text = render_experience(experience)
    if exp_text:
        target_instr += "\n参考经验（上次同类任务的成功做法；若与当前屏幕相符，优先参考）：\n" + exp_text
    if related_apps:
        names = "、".join("%s（%s）" % (ra.get("label"), ra.get("package")) for ra in related_apps)
        target_instr += ("\n本机相关应用：%s。若任务需要用某个应用而现在不在其中，"
                         "优先选「打开应用…」而不是在当前应用里乱点。" % names)
    hint = app_hint_of(cur_pkg)
    if hint:
        target_instr += "\n本 App 使用要点：%s" % hint
    plan_text = render_plan(plan)
    if plan_text:
        target_instr += ("\n" + plan_text +
                         "\n请按此计划推进：若尚未在目标应用内，优先选择「打开应用」；"
                         "达到完成标准时用 done 收尾。")
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
    if ch == "wait":
        return {"action": "wait", "seconds": 2, "confidence": conf}
    if ch == "done":
        return {"action": "done", "confidence": conf}
    return {"action": "wait", "confidence": conf}


MULTI_ANSWER_RE = re.compile(r"前[0-9一二三四五六七八九十]+|[几哪]条|哪些|列表|排名|排行|榜单|都有|全部")


def wants_multi_answer(task, plan):
    """任务是否要求「多条/列表类」答案（前N、哪些、排行…）。
    这类答案 Jev 的单条选择通常不完整 → done 时强制 qwen 汇总全量答案。"""
    texts = [task or "", (plan or {}).get("intent") or "", (plan or {}).get("success") or ""]
    return any(MULTI_ANSWER_RE.search(t) for t in texts)


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn2int(s):
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        return (_CN_NUM.get(a, 1) if a else 1) * 10 + (_CN_NUM.get(b, 0) if b else 0)
    return _CN_NUM.get(s, 0)


def parse_rank_n(text):
    """从任务文本解析"第N条/前N名"的 N（1-99），无则返回 0。"""
    t = text or ""
    m = re.search(r"第\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[条名位个]", t)
    if not m:
        m = re.search(r"前\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[条名位个]?", t)
    if not m:
        return 0
    n = _cn2int(m.group(1))
    return n if 1 <= n <= 99 else 0


def rank_nth(acc, n):
    """从累积榜单（title->热度）取第 n 名（热度降序）的标题。"""
    if len(acc) < n:
        return ""
    items = sorted(acc.items(), key=lambda kv: -kv[1])
    return items[n - 1][0]


def extract_rank_pairs(elems):
    """从屏幕元素提取「标题 + 同一行热度数值」对 → [(score, title), ...]（未排序）。
    背景：微博热搜等榜单的「1/2/3」序号与「置顶」标记是自绘图形、不在无障碍数据里，
    只能靠「热度值」推断官方名次（置顶/推广条目无热度值 → 自动被排除）。"""
    nums = []
    for e in elems:
        s = str(e[3]).strip()
        m = re.search(r"\d{4,}", s)
        if m:
            digits = re.sub(r"\D", "", s)
            if len(digits) >= 5 and len(digits) >= len(s) * 0.45:
                nums.append((e[2], e[1], int(m.group(0))))
    if len(nums) < 3:
        return []
    out = []
    for (ny, nx, score) in nums:
        best = None
        for e in elems:
            if not str(e[3]).strip():
                continue
            if abs(e[2] - ny) <= 40 and e[1] < nx - 30:
                if re.fullmatch(r"[\d\s,]+", str(e[3]).strip()):
                    continue
                if best is None or abs(e[2] - ny) < abs(best[0] - ny):
                    best = (e[2], str(e[3]).strip())
        if best:
            out.append((score, best[1]))
    return out


def render_rank_items(elems, extra=None):
    """排行候选文本：屏幕提取 + （可选）跨步累积数据合并，按热度降序。
    返回可直接注入 prompt 的文本；非榜单页面且无累积数据时返回空串。"""
    pairs = extract_rank_pairs(elems)
    acc = {}
    for score, title in pairs:
        if title not in acc or acc[title] < score:
            acc[title] = score
    for title, score in (extra or {}).items():
        if title not in acc or acc[title] < score:
            acc[title] = score
    if len(acc) < 3:
        return ""
    items = sorted(acc.items(), key=lambda kv: -kv[1])
    lines = ["%d. %s（热度 %d）" % (i, t, s) for i, (t, s) in enumerate(items[:15], 1)]
    return "\n".join(lines)


def qwen_summary(task, screen_text, intent="", rank_text=""):
    rank_block = ""
    if rank_text:
        rank_block = ("\n\n【官方排名候选】屏幕上的榜单条目（按热度数值降序，即官方名次顺序；"
                      "置顶/推广条目因无热度值已自动排除）：\n%s\n"
                      "如果任务要「前N名/排行」，请优先按以上名次与顺序作答。" % rank_text)
    prompt = ("任务：%s%s\n\n当前屏幕元素：\n%s%s\n\n"
              "请直接给出任务要求的答案（简洁、口语化）。要求：只输出答案本身，"
              "不要输出操作步骤/坐标/操作建议；若答案包含多项（如列表、前N条、多个数值），"
              "请编号逐条列出屏幕上实际显示的内容（从上到下、按屏幕顺序、一条不漏）。"
              "若屏幕是排行榜（如微博热搜榜），按榜单顺序列出任务要求的名次；"
              "置顶条目与广告推广条目不算名次（除非任务就是要置顶内容）。"
              % (task, ("\n（任务理解：%s）" % intent) if intent else "", screen_text[:3000], rank_block))
    return call_llm([{"role": "user", "content": prompt}])


def qwen_verify(task, summary, screen_text, intent=""):
    """复核 done：summary 的关键信息能否在屏幕文本中找到依据（防幻觉）+ 内容类型是否匹配任务。
    intent = 规划阶段纠正后的任务理解（避免语音错别字干扰判定）。
    返回 (ok, reason)；复核本身失败时一律放行（不阻塞正常收尾）。"""
    prompt = ("任务：%s%s\n\n待核实的结果：%s\n\n当前屏幕文本：\n%s\n\n"
              "请判断：以上结果是否【真正回答了任务】？以下条件都要满足：\n"
              "① 结果里的关键信息（名称/数字/列表项）能在当前屏幕文本中找到依据（找不到=幻觉，判 false）；\n"
              "② 内容类型与任务要求一致（例：任务要「热搜榜」，结果必须是热搜列表，"
              "普通帖子流/推荐内容不算；任务要「电量」，结果必须是电池数值）。\n"
              "结果若只是操作建议/步骤说明（而非实际查询到的内容），判 false。\n"
              "③ 若任务要求查看/查询具体内容（新闻、列表、热点、多条信息等），结果必须列出至少一条"
              "实际内容（标题/名称/数值）；只说「已找到」「包含多条」而没有具体条目，判 false。\n"
              "④ 结果的主题/来源必须与任务点名的对象一致：任务是「看华尔街见闻的头条新闻」，"
              "结果就必须是「华尔街见闻」的新闻内容；来自其他来源或内容主题不符"
              "（如别的网站/页面的股票行情数据）一律判 false。\n"
              "⑤ 若任务要求「排行/榜单/前N名/热搜榜」，结果必须来自明确的排行榜——"
              "条目带排名序号（1、2、3…）或明确名次，且名次从第 1 名开始连续；"
              "个性化推荐流 / 猜你喜欢 / 雷达流 / 顺序随机的列表不算排行，判 false。\n"
              "只输出一个 JSON：{\"ok\": true 或 false, \"reason\": \"一句话理由\"}"
              % (task, ("\n（任务理解：%s）" % intent) if intent else "", summary[:400], screen_text[:3000]))
    reply = call_llm([{"role": "user", "content": prompt}])
    t = re.sub(r"<think[^>]*>.*?</think[^>]*>", " ", reply, flags=re.S)
    cands = re.findall(r"\{[^{}]*\}", t, re.S)
    if not cands:
        return True, ""
    # 取最后一个含 ok 字段的 JSON（模型可能先输出分析对象、最后才给结论；防首对象误判）
    for cand in reversed(cands):
        try:
            d = json.loads(cand)
        except Exception:
            continue
        if isinstance(d, dict) and "ok" in d:
            return bool(d.get("ok", True)), str(d.get("reason", ""))[:120]
    return True, ""


def qwen_plan(task, apps):
    """开工前规划（2026-09-24 新增）：qwen 先理解任务（纠正语音同音字/错别字）
    → 从已安装清单里选目标 App → 列出执行计划与完成标准。
    返回 dict 或 None（失败时静默跳过，不阻塞任务）。"""
    app_lines = "、".join(
        "%s(%s)" % (a.get("label"), a.get("packageName")) for a in (apps or [])[:150])
    prompt = (
        "你是手机自动化任务的规划器。用户用语音输入，任务文本可能有同音字/错别字，"
        "请先理解真实意图（例如「开盘了APP」很可能是指「开盘啦」App；「胎盘」可能是「盘面/开盘啦」）。\n\n"
        "任务原文：%s\n\n本机已安装应用（名称(包名)）：\n%s\n\n"
        "注意：若任务点名的应用/来源本机没有安装，app_label 与 app_package 填 null，"
        "并在 fallback 里给出替代方案（优先：用「浏览器」打开其官网或搜索该来源）。\n"
        "请只输出一个 JSON（不要多余文字、不要 markdown）：\n"
        "{\"intent\": \"一句话说明用户想要什么（已纠正错别字）\", "
        "\"app_label\": \"完成任务最需要的应用名（必须来自上面清单；没有则 null）\", "
        "\"app_package\": \"对应包名（必须来自上面清单；没有则 null）\", "
        "\"plan\": [\"第1步\", \"第2步\", \"第3步\", \"第4步\"], "
        "\"success\": \"屏幕上出现什么即算完成（一句话）\", "
        "\"fallback\": \"若目标应用不存在或打不开，用什么替代方案（如用浏览器搜索XX）\"}"
        % (task[:400], app_lines[:2500]))
    reply = call_llm([{"role": "user", "content": prompt}])
    t = re.sub(r"<think[^>]*>.*?</think[^>]*>", " ", reply, flags=re.S)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    pk = str(d.get("app_package") or "").strip()
    label = str(d.get("app_label") or "").strip()
    real = ""
    if pk:
        if any(str(a.get("packageName")) == pk for a in apps):
            real = pk
        else:
            real = resolve_package(pk, apps) or ""
    if not real and label:
        for a in apps:
            if str(a.get("label") or "") == label:
                real = str(a.get("packageName") or "")
                break
    d["app_package"] = real
    d["app_label"] = label
    return d


def render_plan(plan):
    """规划 → 注入两引擎 prompt 的文本块（Jev 与 qwen 共用）。"""
    if not plan:
        return ""
    lines = []
    if plan.get("intent"):
        lines.append("【任务理解】%s" % plan["intent"])
    if plan.get("app_package"):
        lines.append("【目标应用】%s（%s）——当前不在其中时优先用「打开应用」进入"
                     % (plan.get("app_label") or "", plan["app_package"]))
    else:
        fb = ("；备用方案：%s" % plan.get("fallback")) if plan.get("fallback") else ""
        lines.append("【目标应用】本机未安装该应用，不要臆造包名%s" % fb)
    if plan.get("plan"):
        lines.append("【执行计划】" + " → ".join(str(s) for s in plan["plan"][:8]))
    if plan.get("success"):
        lines.append("【完成标准】%s" % plan["success"])
    return "\n".join(lines)


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
    """从本地经验库检索与当前任务相似的历史轨迹（成功范例 + 失败教训）。"""
    data = []
    for path in (EXAMPLES_PATH, FAILURES_PATH):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, list):
                data.extend(d)
        except Exception:
            pass
    if not data:
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


_FAILURE_MARKS = ("无法", "未显示", "未找到", "找不到", "看不到", "没能", "没找到", "未能", "失败")


def save_experience(task, result, steps, engine):
    """任务成功后保存轨迹（按任务文本去重置顶，上限 50 条）。
    ①结果里带"失败话术"的（如"未显示/无法查看"）不算成功经验，直接丢弃；
    ②轨迹清洗：去掉 wait，连续相同的 scroll/swipe 只留 1 条（防止把"滚动刷屏"当经验教坏下次）。"""
    if not task or not steps:
        return
    if any(w in (result or "") for w in _FAILURE_MARKS):
        print("[agent] 结果含失败话术，不沉淀成功经验（转入失败教训）")
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
        cleaned = []
        for s in steps[-20:]:
            if str(s).startswith("wait"):
                continue
            if cleaned and s == cleaned[-1] and (str(s).startswith("scroll") or str(s).startswith("swipe")):
                continue
            cleaned.append(s)
        data = [d for d in data if d.get("task") != task]
        data.insert(0, {"task": task, "result": (result or "")[:200], "engine": engine,
                        "steps": cleaned[-20:], "ts": int(time.time())})
        with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
            json.dump(data[:50], f, ensure_ascii=False, indent=1)
        # 任务已成功 → 从错题本移除同类任务（避免"成功经验 + 失败教训"同时注入的矛盾）
        try:
            if os.path.exists(FAILURES_PATH):
                with open(FAILURES_PATH, encoding="utf-8") as f:
                    fails = json.load(f)
                if isinstance(fails, list):
                    kept = [x for x in fails if x.get("task") != task]
                    if len(kept) != len(fails):
                        with open(FAILURES_PATH, "w", encoding="utf-8") as f:
                            json.dump(kept, f, ensure_ascii=False, indent=1)
                        print("[agent] 错题本已清理同类任务（%s）" % task[:30])
        except Exception:
            pass
    except Exception:
        pass


def render_experience(exps):
    """经验列表 → 可注入 prompt 的文本（成功范例 / 失败教训）。"""
    if not exps:
        return ""
    lines = []
    for i, ex in enumerate(exps, 1):
        if ex.get("kind") == "failure":
            lines.append("%d) 上次「%s」失败过（原因：%s）。以下做法当时没奏效，避免重复：" % (
                i, ex.get("task", "")[:36], (ex.get("reason") or "未完成")[:30]))
            for s in (ex.get("steps") or [])[:8]:
                lines.append("   × %s" % s)
        else:
            lines.append("%d) 上次「%s」的做法（%d 步，结果：%s）：" % (
                i, ex.get("task", "")[:36], len(ex.get("steps") or []), (ex.get("result") or "")[:40]))
            for s in (ex.get("steps") or [])[:12]:
                lines.append("   %s" % s)
    lines.append("（注：经验仅供参考操作路径；作答必须以当前屏幕的实际内容为准，不得照抄旧结果。）")
    return "\n".join(lines)


def save_failure(task, reason, steps):
    """任务失败时保存教训（按任务文本去重置顶，上限 30 条），下次同类任务注入"别再做"。"""
    if not task or not steps:
        return
    try:
        os.makedirs(SKILLS_DIR, exist_ok=True)
        try:
            with open(FAILURES_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
        if not isinstance(data, list):
            data = []
        data = [d for d in data if d.get("task") != task]
        data.insert(0, {"task": task, "kind": "failure", "reason": (reason or "")[:80],
                        "steps": steps[-12:], "ts": int(time.time())})
        with open(FAILURES_PATH, "w", encoding="utf-8") as f:
            json.dump(data[:30], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def learn_app_hint(task, exec_log, state, apps=None):
    """任务成功后：qwen 归纳一条「App 使用要点」写入 ~/bridge/skills/apps.json（自我进化）。
    下次同类任务会作为捷径提示注入 Jev/qwen。
    apps 传入已安装清单时做校验：包名不在清单里（模型臆造）→ 不沉淀。"""
    try:
        if not task or not exec_log:
            return
        steps_text = " → ".join(exec_log[-10:])
        pk = ""
        m = re.search(r"open_app\(([\w.]+)\)", steps_text)
        if m:
            pk = m.group(1)
        if not pk:
            try:
                pk = (state.get("phone_state") or {}).get("packageName") or ""
            except Exception:
                pk = ""
        if not pk:
            return
        if apps and all(str(a.get("packageName")) != pk for a in apps):
            return   # 包名不在已安装清单（幻觉包名，如 com.wallstreetcn）→ 不沉淀
        # 手册卡保护：含实测坐标（spots）的 App 卡片为人工维护，自动学习不覆盖其要点
        try:
            if (app_cards().get(pk) or {}).get("spots"):
                print("[agent] App 要点跳过（%s 为手工维护卡，自动学习不覆盖）" % pk)
                return
        except Exception:
            pass
        prompt = ("任务「%s」在 App（%s）上成功完成，执行步骤：%s\n"
                  "请总结一条「App 使用要点」（30 字内）。要求：通用、与具体任务无关——"
                  "只写这个 App 的界面结构/入口位置/操作方式（如「底部导航第三个是发现」「搜索框在顶部」），"
                  "不要写具体任务的搜索词或内容（例如不要写「搜索XX」）。"
                  "只输出 JSON：{\"hint\": \"...\"}" % (task[:80], pk, steps_text[:500]))
        reply = call_llm([{"role": "user", "content": prompt}])
        t = re.sub(r"<think[^>]*>.*?</think[^>]*>", " ", reply, flags=re.S)
        m2 = re.search(r"\{[^{}]*\}", t, re.S)
        if not m2:
            return
        hint = str(json.loads(m2.group(0)).get("hint", "")).strip()
        if len(hint) < 6:
            return
        path = os.path.expanduser("~/bridge/skills/apps.json")
        data = {}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                data = d
        except Exception:
            pass
        old = str(data.get(pk, ""))
        if hint not in old:
            data[pk] = ((old + " " + hint).strip() if old else hint)[:300]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print("[agent] App 要点已更新: %s -> %s" % (pk, hint[:60]))
    except Exception as e:
        print("[agent] App 要点归纳失败: %r" % (e,))


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
def bridge_cmd(cmd, timeout=8.0):
    """经 root 桥（xgt-bridge.sh）执行命令：返回 "ok" 或 "err:..."。
    协议：写 ~/bridge/.xgt_req（"<seq> <cmd>"）→ 桥执行 → 读 ~/bridge/.xgt_res。"""
    req = os.path.expanduser("~/bridge/.xgt_req")
    res = os.path.expanduser("~/bridge/.xgt_res")
    seq = "c%d" % int(time.time() * 1000)
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


def bridge_elements(timeout=8.0):
    """经 root 桥 + 小工头 App 取完整 a11y 树（含"不重要"视图，如微博信息流）。
    替代 uiautomator：实测 uiautomator dump 会触发系统解绑 portal 的 a11y 服务。"""
    out = os.path.expanduser("~/bridge/.tree.json")
    try:
        try:
            os.remove(out)
        except OSError:
            pass
        r = bridge_cmd("tree", timeout=timeout)
        if not r.startswith("ok"):
            print("[agent] 桥取树失败: %s" % r)
            return []
        with open(out, encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        raw = []
        for e in d.get("elems") or []:
            try:
                raw.append((0, int(e[1]), int(e[2]), str(e[3]), bool(e[4])))
            except Exception:
                continue
        if len(raw) < 3:
            return []
        # 限流：可点优先（80）+ 文本（40）
        clicks = [e for e in raw if e[4]][:80]
        texts = [e for e in raw if not e[4] and len(e[3]) >= 2][:40]
        merged = clicks + texts
        return [(i, e[1], e[2], e[3], e[4]) for i, e in enumerate(merged)]
    except Exception as e:
        print("[agent] 桥取树失败: %r" % (e,))
        return []


def fake_tree_from_elems(elems):
    """把元素列表合成一棵最小 a11y_tree（供 render_tree 渲染给 qwen，portal 离线时用）"""
    children = []
    for _, cx, cy, label, clk in elems:
        children.append({"text": label, "className": "", "isClickable": clk,
                         "boundsInScreen": {"left": cx - 1, "top": cy - 1,
                                            "right": cx + 1, "bottom": cy + 1}})
    return {"children": children}


# 登录/验证类敏感操作护栏（安全：agent 不处理登录凭证）
LOGIN_WORDS = ("登录", "验证码", "密码", "注册账号", "一键登录")
DANGER_WORDS = ("验证码", "密码")


def label_at(elems, x, y, tol=70):
    """返回屏幕坐标附近元素的文本（供安全护栏比对）"""
    for e in elems:
        if abs(e[1] - x) <= tol and abs(e[2] - y) <= tol:
            return e[3]
    return ""


# ---------------------------------------------------------------- App 使用要点（经验卡雏形）
APP_HINTS_BUILTIN = {
    "com.sina.weibo": {
        "hint": ("看【真实热搜排行】三步（2026-09-24 真机实测）："
                 "① 底部导航点「发现」；"
                 "② 发现页热搜卡片右下角点「更多热搜」（坐标约 (907,846)）；"
                 "③ 进入后默认停在「我的」标签=个性化雷达（不是排行！），"
                 "必须再点顶部标签栏第 2 个「热搜」（坐标约 (267,624)）→ 出现"
                 "「实时热点，每分钟更新一次」+ 带编号 1、2、3… 的榜单，这才是真正的热搜排行。"
                 "注意：发现页卡片、「我的」标签页都是个性化内容（顺序随机），不算排行；"
                 "真榜条目名后带热度数字（如 1090896）。"
                 "若停在其它页面（搜索页/详情页/直播页等）：按返回键，或点底部导航"
                 "「发现」(540,2277) 回到发现页再走上面的路径；底部导航固定："
                 "首页(108,2277) / 视频(324,2277) / 发现(540,2277) / 消息(756,2277) / 我(972,2277)。"
                 "若底部中部显示「回到顶部」浮动按钮，先点它一次再点「发现」。"),
        "spots": [
            ["更多热搜(发现页热搜卡片右下角)", 907, 846, ["更多热搜", "热搜简报"]],
            ["热搜排行标签(顶部标签栏第2个)", 267, 624, ["热搜雷达"]],
        ],
    },
    "com.android.settings": "设置项都在首屏列表；找不到就向下滑动。电池电量：设置 → 电池。",
    "com.coloros.weather2": "打开即见当前温度与天气；未来几天预报向下滑动。",
    "com.tencent.mm": "底部导航（左→右）：微信 / 通讯录 / 发现 / 我。若显示登录页则无法查看消息。",
    "com.aiyu.kaipanla": {
        "hint": ("看市场数据：①「市场情绪」= 首页第 1 行第 2 个图标（约 (405,342)）→ "
                 "首屏「涨跌统计」直接显示「实际涨停: N 家（过滤ST股）」「实际跌停: N 家」；"
                 "②「龙虎榜」= 底部导航第 2 个 tab（约 (740,2281)）→ 今日上榜股票列表；"
                 "③ 首页第 1 行第 1 个图标是「实时龙虎榜」。"
                 "注意：打开 App 可能恢复上次的详情页（如市场情绪），若不在首页先按返回键回首页；"
                 "首页特征：图标区含「实时龙虎榜/市场情绪/复盘啦/题材库」。"
                 "底部导航：自选股 / 龙虎榜 / 推荐 / 行情。"),
        "spots": [
            ["市场情绪(开盘啦首页第1行第2个图标)", 405, 342, ["实时龙虎榜", "题材库"]],
            ["龙虎榜(底部导航第2个)", 740, 2281, ["自选股", "龙虎榜", "行情"]],
        ],
    },
    "com.ss.android.article.news": {
        "hint": ("看某个板块（财经/军事/国际等）：顶部频道栏（y≈313）直接点对应频道——"
                 "「财经」约 (445,313)、「军事」(599,313)、「国际」(752,313)；"
                 "频道栏可左右滑动查看更多。顶栏下方就是该板块的信息流；顶部搜索框约 (654,181)。"
                 "启动后可能停在别的板块（如短剧），点频道切回即可。"),
        "spots": [
            ["财经频道(今日头条顶部频道栏)", 445, 313, ["财经", "军事", "国际"]],
        ],
    },
}
_APP_CARDS = None


def normalize_app_card(v):
    """统一 App 卡片格式 → {"hint": str, "spots": [{"label","x","y","whens"}]}
    支持 str（纯提示文本）或 dict（{"hint":..., "spots": [["label",x,y,["特征词"...]], ...]}）。"""
    if isinstance(v, str):
        return {"hint": v, "spots": []}
    if isinstance(v, dict):
        spots = []
        for s in (v.get("spots") or []):
            try:
                spots.append({"label": str(s[0]), "x": int(s[1]), "y": int(s[2]),
                              "whens": [str(w) for w in (s[3] if len(s) > 3 else [])]})
            except Exception:
                pass
        return {"hint": str(v.get("hint") or ""), "spots": spots}
    return {"hint": "", "spots": []}


def app_cards():
    """App 经验卡（统一格式，含坐标补丁 spots）= 内置 + ~/bridge/skills/apps.json（外部可覆盖/补充）。
    外部若给 str，只覆盖 hint、保留内置 spots；给 dict 则整体覆盖。"""
    global _APP_CARDS
    if _APP_CARDS is None:
        cards = {str(k): normalize_app_card(v) for k, v in APP_HINTS_BUILTIN.items()}
        try:
            with open(os.path.expanduser("~/bridge/skills/apps.json"), encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                for k, v in d.items():
                    k = str(k)
                    if isinstance(v, dict):
                        cards[k] = normalize_app_card(v)
                    else:
                        old = cards.get(k) or {"hint": "", "spots": []}
                        cards[k] = {"hint": str(v), "spots": old.get("spots") or []}
        except Exception:
            pass
        _APP_CARDS = cards
    return _APP_CARDS


def app_hint_of(pkg):
    """当前 App 的文字要点（给 Jev/qwen 的提示词用）。"""
    c = app_cards().get(pkg or "")
    return (c or {}).get("hint") or ""


def app_coords(pkg, elems):
    """App 经验坐标：页面特征词出现时，把实测坐标作为虚拟元素返回（Jev/qwen 可直接选用点击）。
    - pkg 非空：只看该 App 的卡片；pkg 为空（portal 离线）：扫描全部卡片（靠特征词过滤）。
    - 防重复：屏幕上已有坐标接近且同名元素时跳过。"""
    cards = app_cards()
    if pkg:
        cand = [cards.get(pkg) or {}]
    else:
        cand = list(cards.values())
    labels = "|".join(str(e[3]) for e in elems)
    out = []
    for card in cand:
        for sp in (card.get("spots") or []):
            whens = sp.get("whens") or []
            if whens and not any(w and (w in labels) for w in whens):
                continue
            dup = any(abs(e[1] - sp["x"]) < 40 and abs(e[2] - sp["y"]) < 40
                      and sp["label"][:4] in str(e[3]) for e in elems)
            if not dup:
                out.append(sp)
    return out


# 内容区常被 a11y 过滤的 App（即使 portal 元素数不低，也强制 uiautomator 补盲）
BLIND_APPS_BUILTIN = {"com.sina.weibo"}
_BLIND_APPS = None


def blind_apps():
    """需要强制感知补盲的 App 集合 = 内置 + ~/bridge/skills/blind_apps.json（list）"""
    global _BLIND_APPS
    if _BLIND_APPS is None:
        _BLIND_APPS = set(BLIND_APPS_BUILTIN)
        try:
            with open(os.path.expanduser("~/bridge/skills/blind_apps.json"), encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, list):
                _BLIND_APPS.update(str(x) for x in d)
        except Exception:
            pass
    return _BLIND_APPS


def resolve_package(want, apps):
    """把模型给出的包名解析成本机真实包名（精确 → 有意义段模糊）。
    例：com.miui.weather → com.coloros.weather2（本机天气 App）。
    注意：只匹配包名里"有意义的段"（排除 com/app 等通用词），
    避免 "com.xxx.app" 的尾段 "app" 匹配到 com.jingdong.app.mall 这类灾难（2026-09-24 实证）。
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
    generic = {"com", "cn", "net", "org", "android", "app", "apps", "mobile", "client",
               "lite", "pro", "hd", "main", "phone", "pad", "plus", "free", "inc"}
    segs = [s for s in w.split(".") if len(s) >= 4 and s not in generic]
    for key in sorted(segs, key=len, reverse=True):
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


def decide(step, task, state, history, engine_now, elems, experience=None, related_apps=None, plan=None):
    """返回 (act, engine_name, seconds, trace_info)。trace_info = {"prompt":..., "reply":...}"""
    t0 = time.time()
    if engine_now == "jev":
        try:
            cur_pkg = ""
            try:
                cur_pkg = (state.get("phone_state") or {}).get("packageName") or ""
            except Exception:
                pass
            answers = jev_decide(task, elems, history, experience, related_apps, cur_pkg, plan)
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
    screen = render_elems(elems) if elems else render_tree(state)
    exp_text = render_experience(experience)
    exp_block = ("\n\n参考经验（上次类似任务的成功做法，可借鉴；若与实际屏幕不符则忽略）：\n" + exp_text) \
        if exp_text else ""
    app_hint = ""
    if related_apps:
        app_hint = "\n\n本机可用应用：" + "、".join(
            "%s(%s)" % (ra.get("label"), ra.get("package")) for ra in related_apps) + \
            "。如需打开应用请严格使用以上包名（不要臆造别的包名）。"
    app_note = ""
    try:
        _pk = (state.get("phone_state") or {}).get("packageName") or ""
        _h = app_hint_of(_pk)
        if _h:
            app_note = "\n\n本 App 使用要点：%s" % _h
    except Exception:
        pass
    plan_text = render_plan(plan)
    plan_block = ("\n\n" + plan_text) if plan_text else ""
    user = ("任务: %s%s\n\n第 %d 步。当前屏幕元素清单：\n%s%s%s%s\n\n"
            "请输出下一步动作 JSON。" % (task, plan_block, step, screen, exp_block, app_hint, app_note))
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
    no_effect = {}     # tap 签名 -> 连续"屏幕无变化"次数（>=2 视为无效点击）
    last_sig, last_ok, last_hash = None, None, None
    block_streak = 0   # 连续被系统拒绝的次数
    done_rejects = 0   # done 被防幻觉复核驳回的次数（上限 2）
    scroll_streak = 0  # 连续滚动/滑动次数（迷路检测：≥6 次强制升级）
    last_sw_sig, sw_repeat = None, 0  # 连续相同滑动检测（≥3 软提醒，≥7 硬阻断）
    login_warned = False  # 登录页提示只发一次
    rank_acc = {}      # 榜单跨步累积：title -> 最高热度（滚动收集"第N条"类任务用）
    rank_ready = False       # 榜单收集足够（已提示可直接作答）
    rank_collect_hint = False  # 榜单收集催促（只发一次）
    kb_switched = False        # 键盘弹出已触发 qwen 接管（只触发一次）

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
    # —— 开工前规划：qwen 先理解任务（纠同音字）+ 从清单选目标 App + 列计划（2026-09-24 新增） ——
    plan = None
    try:
        plan = qwen_plan(task, apps)
    except Exception as e:
        print("[agent] 规划阶段失败（跳过）: %r" % (e,))
    if plan:
        print("[agent] 任务理解: %s" % ((plan.get("intent") or "-")[:120]))
        if plan.get("app_package"):
            print("[agent] 目标应用: %s(%s)" % (plan.get("app_label"), plan["app_package"]))
        else:
            print("[agent] 目标应用: 本机未安装（备用方案: %s）" % ((plan.get("fallback") or "-")[:80]))
        if plan.get("plan"):
            print("[agent] 计划: %s" % " → ".join(str(s) for s in plan["plan"][:8]))
        tracer.log(0, "result", "规划: " + json.dumps(plan, ensure_ascii=False)[:600])
        if plan.get("app_package"):
            if all(ra.get("package") != plan["app_package"] for ra in related_apps):
                related_apps = [{"label": plan.get("app_label") or plan["app_package"],
                                 "package": plan["app_package"]}] + related_apps
        else:
            fb = str(plan.get("fallback") or "")
            if any(w in fb for w in ("浏览器", "网页", "网站", "搜索")):
                for a in apps:
                    if str(a.get("label") or "") == "浏览器":
                        if all(ra.get("package") != a.get("packageName") for ra in related_apps):
                            related_apps = related_apps + [{"label": a.get("label"),
                                                            "package": a.get("packageName")}]
                        break
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
        pre_elems = None
        if state is None:
            # portal 不可用 → 用 root 桥树顶上（操作侧由 Portal 的桥兜底接续）
            pre_elems = bridge_elements()
            if pre_elems:
                print("[step %d] portal 不可用，转用 root 桥树（%d 元素）" % (step, len(pre_elems)))
                tracer.log(step, "result", "portal离线→桥树 %d 元素" % len(pre_elems))
                state = {"phone_state": {"currentApp": "(桥)", "packageName": "",
                                         "keyboardVisible": False},
                         "a11y_tree": fake_tree_from_elems(pre_elems)}
            else:
                print("[agent] portal 连续取状态失败且桥树也不可用，中止。")
                aborted = True
                break
        elems = collect_elements(state)
        cur_pkg = ""
        try:
            cur_pkg = (state.get("phone_state") or {}).get("packageName") or ""
        except Exception:
            pass
        if pre_elems is not None:
            elems = pre_elems
        else:
            # —— 感知补盲：portal 树元素过少（内容区被标记"不重要"被过滤）→ 用 root 桥完整树 ——
            if len(elems) < 8 or cur_pkg in blind_apps():
                extra = bridge_elements()
                if len(extra) > len(elems):
                    print("[step %d] 感知补盲: portal %d -> 桥树 %d 元素"
                          % (step, len(elems), len(extra)))
                    tracer.log(step, "result", "感知补盲 %d->%d 元素" % (len(elems), len(extra)))
                    elems = extra
        # —— 经验坐标注入：App 卡片实测坐标（如微博「更多热搜」「热搜」标签）→ 虚拟元素（Jev/qwen 可直接点） ——
        try:
            for _sp in app_coords(cur_pkg, elems):
                elems.append((len(elems), _sp["x"], _sp["y"],
                              "%s【经验坐标】" % _sp["label"], True))
                print("[step %d] 经验坐标注入: %s (%d,%d)"
                      % (step, _sp["label"], _sp["x"], _sp["y"]))
                tracer.log(step, "result", "经验坐标注入: %s (%d,%d)"
                           % (_sp["label"], _sp["x"], _sp["y"]))
        except Exception:
            pass
        # —— 榜单跨步累积：把本屏可见的「标题+热度」并入累积器（滚动收集"第N条"类任务用） ——
        try:
            for _score, _title in extract_rank_pairs(elems):
                if _title not in rank_acc or rank_acc[_title] < _score:
                    rank_acc[_title] = _score
        except Exception:
            pass
        screen_hash = hash(tuple((e[3][:24], e[1] // 16, e[2] // 16) for e in elems))

        # —— 上一步效果补记：用本步屏幕对比上一步执行后的变化，回传给模型（治"点了没反应还在点"） ——
        if last_sig is not None:
            changed = (screen_hash != last_hash)
            if last_ok and not changed:
                if last_sig[0] in ("tap", "open_app"):
                    no_effect[last_sig] = no_effect.get(last_sig, 0) + 1
                note = "（系统补充）上一步动作已执行，但屏幕没有任何变化——可能没生效/无效。"
                if last_sig[0] in ("tap", "open_app") and no_effect.get(last_sig, 0) >= 2:
                    note += ("该操作已连续 %d 次无效果，请不要再重复，换一种做法。"
                             % no_effect[last_sig])
                    tracer.log(step, "result", "无效操作标记: %s" % (last_sig,))
                history.append({"role": "user", "content": note})
            elif changed:
                no_effect.clear()   # 屏幕已变化（加载完成/页面切换）→ 解除全部"无效"标记
            last_sig = None
        # —— 榜单收集推进："第N条/前N名"任务：数据不足时催促滚动，足够时直接给出名次 ——
        _rn = parse_rank_n(task) or parse_rank_n((plan or {}).get("intent") or "")
        if _rn and step >= 2:
            if len(rank_acc) >= _rn + 2:
                if not rank_ready:
                    _nth = rank_nth(rank_acc, _rn)
                    if _nth:
                        history.append({"role": "user", "content":
                                        "（系统提醒）榜单数据已收集足够（%d 条）。按官方顺序（热度降序）"
                                        "第 %d 条是：%s。如果任务就是问这一条，请直接输出 done 并给出该答案。"
                                        % (len(rank_acc), _rn, _nth)})
                        print("[step %d] 榜单收集完成: 第%d条 = %s" % (step, _rn, _nth[:40]))
                        rank_ready = True
            elif not rank_collect_hint and step >= 3:
                history.append({"role": "user", "content":
                                "（系统提醒）这是榜单任务（要第 %d 条），当前已收集 %d 条数据，还不足。"
                                "请向下滚动榜单继续查看更多条目；系统会自动记录滚动过的条目。"
                                % (_rn, len(rank_acc))})
                rank_collect_hint = True

        # —— 键盘弹出 = 需要文字输入（Jev 无 input_text 能力）→ 立即升级 qwen（决策前切换） ——
        if (mode == "auto" and engine_now == "jev" and not kb_switched
                and bool((state.get("phone_state") or {}).get("keyboardVisible"))):
            kb_switched = True
            engine_now = "qwen"
            prog.score = 0
            history.append({"role": "user", "content":
                            "（系统）输入法键盘已弹出（需要输入文字）。由更强的模型接管："
                            "请用 input_text 输入任务所需的关键词，"
                            "再按 ENTER(键码 66) 或点「搜索」按钮提交，最后读取结果。"})
            print("[step %d] 键盘弹出 → qwen 接管（需要文字输入）" % step)

        # —— 阶段性终点检查：每 6 步提醒引擎查看"答案是否已在屏幕上" ——
        if step > 1 and step % 6 == 1:
            history.append({"role": "user", "content":
                            "（系统提醒）请先仔细看当前屏幕：任务要求的信息（名称/数值/列表等）"
                            "是否已经出现？如果已经能看到，请立即输出 done，并在 summary 里给出答案；"
                            "如果没有，再继续操作。"})
        # —— 登录页检测：只提醒不登录（安全护栏另见执行处） ——
        if not login_warned and step >= 3:
            try:
                hit = sum(1 for e in elems if any(w in e[3] for w in LOGIN_WORDS))
                if hit >= 3:
                    login_warned = True
                    print("[step %d] 检测到登录页（%d 个登录关键词）" % (step, hit))
                    tracer.log(step, "result", "登录页检测：不执行登录操作")
                    history.append({"role": "user", "content":
                                    "（系统检测）当前界面似乎是登录/验证页。请不要尝试登录、获取验证码或"
                                    "输入账号密码；如果任务需要登录才能继续，请直接输出 done，并在 summary 中"
                                    "说明「无法完成：需要先登录」。"})
            except Exception:
                pass
        try:
            act, eng, dec_dt, ti = decide(step, task, state, history, engine_now, elems,
                                          experience, related_apps, plan)
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
            # 榜单单条任务（"第N条"）：累积数据足以确定名次 → 以系统确定答案为准（防模型猜错）
            sys_locked = False
            try:
                m_nth = re.search(r"第\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[条名位个]", task or "")
                if m_nth:
                    _n2 = _cn2int(m_nth.group(1))
                    _sys = rank_nth(rank_acc, _n2)
                    if _sys:
                        summary = "第 %d 条是：%s" % (_n2, _sys)
                        sys_locked = True
                        print("[agent] 榜单第%d条（系统确定）: %s" % (_n2, _sys[:50]))
            except Exception:
                pass
            # 列表类任务（前N/排行/哪些…）：Jev 的单条选择不算完整答案 → 强制 qwen 汇总全量
            multi = wants_multi_answer(task, plan)
            if ((not summary or len(summary) >= 60 or multi) and engine_now != "qwen"
                    and not sys_locked):
                try:
                    polished = qwen_summary(task, render_elems(elems) if elems else render_tree(state),
                                            (plan or {}).get("intent") or "",
                                            render_rank_items(elems or [], extra=rank_acc))
                    if polished:
                        summary = polished
                except Exception as e:
                    if not summary:
                        summary = "(总结生成失败: %r)" % e
            # —— 防幻觉复核：结果须能在屏幕上找到依据（"无法完成"如实报告的直接放行） ——
            screen_text = " ".join(e[3] for e in elems)
            if (summary and done_rejects < 2 and len(screen_text) >= 30
                    and not summary.startswith("无法") and not sys_locked):
                try:
                    v_ok, v_reason = qwen_verify(task, summary, screen_text,
                                                 (plan or {}).get("intent") or "")
                except Exception:
                    v_ok, v_reason = True, ""
                if not v_ok:
                    done_rejects += 1
                    print("[step %d] DONE 被驳回：%s" % (step, v_reason))
                    tracer.log(step, "result", "done被驳回: %s" % v_reason)
                    tracer.log(step, "action", "done(被驳回)")
                    history.append({"role": "assistant",
                                    "content": json.dumps(act, ensure_ascii=False)})
                    history.append({"role": "user", "content":
                                    "你的完成申报被系统驳回：%s。任务尚未真正完成，请继续操作；"
                                    "若任务要求多条内容（前N条/列表/排行），summary 必须逐条列全"
                                    "（如「1. xxx 2. xxx 3. xxx」），只给一条不算完成。"
                                    "如果确实无法完成，请再次输出 done，并在 summary 中如实说明"
                                    "「无法完成：原因」。" % (v_reason or "结果在屏幕上找不到依据")})
                    time.sleep(1.0)
                    continue
            print("[agent] engine-usage: jev=%d qwen=%d" % (usage["jev"], usage["qwen"]))
            print("[agent] DONE: %s" % summary)
            tracer.log(step, "done", summary)
            tracer.close()
            if exec_log:
                save_experience(task, summary, exec_log, mode)
                print("[agent] 经验已保存: %d 步 → ~/bridge/skills/examples.json" % len(exec_log))
                if not (summary or "").startswith("无法"):
                    try:
                        learn_app_hint(task, exec_log, state, apps)
                    except Exception:
                        pass
            return 0

        # —— 重复失败/无效动作硬阻断（连续失败 ≥2 或连续无效果 ≥2 → 拒绝执行，逼模型换策略） ——
        sig = Progress.sig_of(act)
        # 连续相同滑动检测（任意引擎）：≥3 软提醒，≥7 硬阻断（治"同一滑动刷 15 次"的迷路）
        sw_sig = None
        if a == "swipe":
            sw_sig = ("swipe", int(act.get("x1", 0)) // 16, int(act.get("y1", 0)) // 16,
                      int(act.get("x2", 0)) // 16, int(act.get("y2", 0)) // 16)
        elif a == "scroll":
            sw_sig = ("scroll", (act.get("direction") or "down").lower())
        if sw_sig is not None and sw_sig == last_sw_sig:
            sw_repeat += 1
        elif sw_sig is not None:
            last_sw_sig, sw_repeat = sw_sig, 1
        else:
            last_sw_sig, sw_repeat = None, 0
        sw_blocked = sw_sig is not None and sw_repeat >= 7
        _fail_lim = 3 if (sig is not None and sig[0] == "open_app") else 2
        blocked = (sig is not None and (fail_counts.get(sig, 0) >= _fail_lim
                                        or no_effect.get(sig, 0) >= 2)) or sw_blocked
        if blocked:
            ok = False
            if sw_blocked:
                exec_err = "相同滑动已连续 %d 次未到达目标" % sw_repeat
                print("[step %d] BLOCK 滑动迷路: %s" % (step, sw_sig))
            else:
                exec_err = "该动作已连续多次失败/无效果（很可能无效/目标不存在）"
                print("[step %d] BLOCK 重复失败动作: %s" % (step, sig))
        else:
            try:
                if a == "tap":
                    tgt = act.get("pick") or label_at(elems, act.get("x", -1), act.get("y", -1))
                    if tgt and any(w in tgt for w in DANGER_WORDS):
                        ok = False
                        exec_err = ("安全护栏：不执行「%s」类操作（agent 不处理登录/验证码凭证）" % tgt)
                        print("[step %d] 护栏拦截: %s" % (step, tgt))
                        tracer.log(step, "result", "护栏拦截: %s" % tgt)
                    else:
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
                        exec_err = ("本机未安装该应用（包名 %s 不存在，已核对全部已安装应用；"
                                    "不要臆造包名）" % want)
                        if related_apps:
                            exec_err += "。可用的相关应用：" + "、".join(
                                "%s(%s)" % (ra["label"], ra["package"]) for ra in related_apps)
                        print("[step %d] open_app 解析失败: %s" % (step, want))
                    else:
                        if real and real != want:
                            print("[step %d] open_app 包名矫正: %s -> %s" % (step, want, real))
                            tracer.log(step, "result", "包名矫正: %s -> %s" % (want, real))
                            act["package"] = real
                        portal.open_app(real or want)
                        time.sleep(3.0)   # App 冷启动等待（大 App 被系统清理后重启需数秒）
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
        # 记录本步，供下一步"效果补记"（屏幕变化对比）
        last_sig, last_ok, last_hash = sig, ok, screen_hash
        # 迷路检测：连续滚动/滑动计数（滚动会改变屏幕哈希，不会触发常规"无进展"）
        if a in ("scroll", "swipe"):
            scroll_streak += 1
        else:
            scroll_streak = 0

        tracer.log(step, "result", ("ok: " if ok else "FAIL: ") + action_to_line(act),
                   ok=ok, ms=int((time.time() - t_step) * 1000), blocked=blocked)
        exec_log.append(action_to_line(act) + ("" if ok else "（失败）"))
        history.append({"role": "assistant", "content": json.dumps(act, ensure_ascii=False)})
        if blocked:
            block_streak += 1
            extra = ""
            if related_apps and a == "open_app":
                extra = " 本机可用的相关应用：" + "、".join(
                    "%s(%s)" % (ra["label"], ra["package"]) for ra in related_apps) + "。"
            if sw_blocked:
                msg = ("上一步没有执行：相同的滑动已连续 %d 次，屏幕仍未到达目标。"
                       "请停止滑动，改用其他方法（按返回键、点击页面导航/按钮、换入口或换 App）。"
                       % sw_repeat)
            else:
                msg = ("上一步没有执行：动作 %s 已被系统拒绝（连续失败/无效果）。"
                       "请换一种完全不同的做法（换应用/换入口/用搜索），不要重复同一动作。%s"
                       % (json.dumps(act, ensure_ascii=False)[:140], extra))
            if block_streak >= 3:
                msg += ("（系统警告：该动作已被连续拒绝 %d 次，坐标已禁用）"
                        "若你认为任务所需的答案已经显示在屏幕上，请立即输出 done 并在 summary 给出答案；"
                        "否则必须彻底改变策略。" % block_streak)
            history.append({"role": "user", "content": msg})
        else:
            block_streak = 0
            history.append({"role": "user", "content":
                            "上一步动作执行%s%s。" % ("成功" if ok else "失败",
                                                      ("：" + exec_err) if (not ok and exec_err) else "")})
            if sw_sig is not None and sw_repeat >= 4:
                history.append({"role": "user", "content":
                                "（系统补充）你已连续 %d 次相同的滑动。若屏幕内容仍在按预期滚动、"
                                "接近目标，可以继续；若反复滑动但内容没有实质变化，"
                                "请立即停止滑动，改用其他方法（按返回键、点击页面上的导航按钮、"
                                "换入口或换 App）。" % sw_repeat})

        flags = prog.note(act, ok, screen_hash)
        if flags:
            print("[step %d] signals: %s (无进展 x%d/%d)" %
                  (step, ",".join(flags), prog.score, upgrade_after))

        if mode == "auto" and engine_now == "jev" and (prog.score >= upgrade_after
                                                       or scroll_streak >= 6):
            print("[switch] %s → qwen 接管（从第 %d 步起）" %
                  ("连续无进展 x%d（%s）" % (prog.score, ",".join(flags) if flags else "-")
                   if prog.score >= upgrade_after else "连续滚动 %d 次（迷路）" % scroll_streak,
                   step + 1))
            engine_now = "qwen"
            prog.score = 0
            scroll_streak = 0
            history.append({"role": "user", "content":
                            "快速引擎连续多步无进展（重复动作/屏幕无变化/连续滚动找不到目标）。"
                            "现在由更强的模型接管：请根据当前屏幕与任务重新规划，避免重复此前无效动作。"
                            "若屏幕上已有任务所需的信息，请直接输出 done 并给出答案。"})
        elif prog.score >= upgrade_after:
            # 已在 qwen 且再次连续无进展 → 迷路重置提示（防"原地打转"，2026-09-24 新增）
            prog.score = 0
            scroll_streak = 0
            print("[step %d] [reset] 连续无进展（%s）→ 注入迷路重置提示" %
                  (step, ",".join(flags) if flags else "-"))
            tracer.log(step, "result", "迷路重置提示: %s" % (",".join(flags) if flags else "-"))
            history.append({"role": "user", "content":
                            "（系统警告）你已连续多步没有进展（%s）。立即改变做法："
                            "①先按返回键回到本应用首页/上级页面（确认看到底部导航或首页内容）；"
                            "②然后按计划重新进入目标页面，优先尝试计划里的另一个入口；"
                            "禁止继续重复上一步动作或原地滑动。"
                            % (",".join(flags) if flags else "重复动作/无进展")})
        time.sleep(0.8)

    print("[agent] engine-usage: jev=%d qwen=%d" % (usage["jev"], usage["qwen"]))
    fail_reason = ""
    if aborted:
        fail_reason = "portal 不可用（中止）"
        print("[agent] FAILED: portal unreachable (aborted).")
    else:
        fail_reason = "步数用尽（%d 步未完成）" % max_steps
        print("[agent] max steps (%d) reached, no done." % max_steps)
    if exec_log:
        save_failure(task, fail_reason, exec_log)
        print("[agent] 失败教训已记录: %d 步 → ~/bridge/skills/failures.json" % len(exec_log))
    tracer.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
