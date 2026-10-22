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
import subprocess
import sys
import time
import urllib.request

PORTAL_BASE = os.environ.get("PORTAL_BASE", "http://127.0.0.1:8080")
LLM_BASE = os.environ.get("LLM_BASE", "http://192.168.3.75:8888/v1")
LLM_KEY = os.environ.get("LLM_KEY", "123")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3.8-flash-next")  # 2026-10-21 实测可用
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

# ---------------------------------------------------------------- 确定性骨架（2026-10-11）
# 三级锚点（包名/Activity → 像素指纹 → 文本特征）+ 五道关卡（开工闸门/起点/路径/步进/收工）
# 每个机制一个独立开关：出问题可单项关闭，不必整体回滚。
try:
    import anchors as AN
except Exception as _e:
    AN = None
    print("[agent] anchors 模块不可用（锚点降级为纯文本）: %r" % (_e,))
try:
    import scripts_lib as SL
except Exception as _e:
    SL = None
    print("[agent] scripts_lib 模块不可用（确定性骨架关闭）: %r" % (_e,))

SW_ANCHORS = os.environ.get("ANCHORS", "1") == "1"      # 三级锚点（Activity / 像素指纹）
SW_GATE    = os.environ.get("GATE", "1") == "1"         # 关卡〇 开工闸门（可行性）
SW_BUDGET  = os.environ.get("BUDGET", "1") == "1"       # 关卡〇 分级预算
SW_FAMILY  = os.environ.get("FAMILIES", "1") == "1"     # 任务家族
SW_HOME    = os.environ.get("HOME_RESET", "1") == "1"   # 关卡一 起点归位
SW_SCRIPT  = os.environ.get("SCRIPT_REPLAY", "1") == "1"  # 关卡二 脚本重放
SW_SKELETON = os.environ.get("SKELETON", "0") == "1"    # 关卡二' 规划骨架确定性执行
#   ⚠️ 2026-10-12 默认**关**：用户定调"速度不是第一考量、准确率优先" —— 新任务**直接走
#   模型逐步决策**（准确率最高），骨架只作为**规划建议**注入 prompt（render_plan），
#   不再作为"廉价先行路径"。骨架执行仅留给实验（SKELETON=1）。
SW_REVIEW  = os.environ.get("RESULT_REVIEW", "1") == "1"  # 关卡四 收工结果复核
SW_SUBGOAL = os.environ.get("SUBGOALS", "1") == "1"     # 关卡三 子目标 + 每步验收
SW_GUARDS  = os.environ.get("GUARDS", "1") == "1"       # 贯穿件 B 硬闸门

SCRIPT_BREAK_HINT = [""]     # 脚本断裂提示（供自由循环注入 history）
_JEV_FAILS = [0]             # jev 连续失败计数（≥2 → 本次运行不再尝试 jev）
try:
    TIME_CAP = float(os.environ.get("TIME_CAP", "300"))   # 单任务总时长上限（秒）；150 太短（成功案例同花顺即用 122s，浏览器任务被误杀）
except Exception:
    TIME_CAP = 150.0
_ACT_CACHE = {"ts": 0.0, "v": ""}
_FP_CACHE = {"ts": 0.0, "v": None}
_HOME_DONE = set()           # 本次运行内已归位过的 App（脚本重放与自由循环共用）

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

SYSTEM_PROMPT = (
    "你是运行在安卓手机里的自动化助手。你会收到当前屏幕上的可访问性元素列表，"
    "每行形如 `[编号] (x,y) 文本 可点`，编号是该元素的唯一编号。\n"
    "你只能输出一个 JSON 对象（不要输出 JSON 以外的任何文字），表示下一步动作：\n"
    '- {"action":"tap","pick":编号} 点击列表里的第 N 号元素（**强烈推荐、最准**；'
    "直接报编号，不要抄坐标、不要猜名字）\n"
    '- {"action":"tap","x":数字,"y":数字} 点击坐标（仅在列表里确实没有该元素时用）\n'
    '- {"action":"swipe","x1":,"y1":,"x2":,"y2":,"duration":500} 滑动（特殊手势才用）\n'
    '- {"action":"scroll","direction":"down" 或 "up"} 滚动页面（**翻页优先用它**，'
    "系统会自动适配屏幕，不要自己编 swipe 坐标；down=看下面的内容，up=回看上面的内容）\n"
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


def call_llm(messages, timeout=90, max_tokens=1024):
    payload = {"model": LLM_MODEL, "messages": messages,
               "temperature": 0.2, "max_tokens": max_tokens}
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


def last_chance_check(task, elems):
    """放弃前最后一眼（迭代8，2026-10-19 抖音热榜误放弃实证）：屏幕其实已到达目标，
    但指纹误判"无变化"导致兜底放弃 → 放弃前把当前屏幕交给 LLM 复查一次，
    若已能回答任务则直接出 done 答案，不白跑。返回答案字符串或 None。"""
    try:
        screen = render_elems(elems) if elems else ""
        if not screen:
            return None
        prompt = ("任务：%s\n当前屏幕元素：\n%s\n\n"
                  "放弃前最后一眼：仅根据以上屏幕元素判断，任务是否其实已经完成/可以回答？\n"
                  "如果可以，只输出 JSON：{\"action\":\"done\",\"summary\":\"<答案或结果>\"}\n"
                  "如果确实还没完成，只输出 JSON：{\"action\":\"wait\"}"
                  % (task, screen[:3000]))
        txt = call_llm([{"role": "user", "content": prompt}], timeout=30, max_tokens=300)
        act = parse_action(txt)
        if act.get("action") == "done" and str(act.get("summary") or "").strip():
            return str(act["summary"]).strip()
    except Exception as e:
        print("[agent] 最后一眼检查异常: %r" % (e,))
    return None


def jev_ask(state, questions, timeout=30):
    payload = {"model": "jev-latest", "state": state, "questions": questions}
    req = urllib.request.Request(JEV_URL, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + JEV_KEY)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def collect_elements(state, limit=110, drop_status_bar=True):
    """a11y 树 → [(idx, cx, cy, label, clickable)]

    2026-10-12：**过滤状态栏**（cy < 110 的时间/电量/通知图标文字）。实测一次 dump 里
    30 个元素有 20 个是状态栏噪声 → 严重稀释模型注意力、并污染"文字锚点"验收。"""
    out = []

    def visit(node):
        if len(out) >= limit or not isinstance(node, dict):
            return
        text = (node.get("text") or "").strip()
        desc = (node.get("contentDescription") or "").strip()
        label = text if text else desc
        clickable = bool(node.get("isClickable") or node.get("isLongClickable") or node.get("isEditable"))
        editable = bool(node.get("isEditable"))
        b = node.get("boundsInScreen") or {}
        # 2026-10-22：**可编辑但没有文字的输入框也要收**。
        # 实测（B站HD 搜索页）：AutoCompleteTextView 有 isEditable 但 text 为空，
        # 被原逻辑过滤掉 → 模型认为"页面没有输入框"，只会反复点搜索栏，永远走不到 input_text。
        if not label and editable:
            label = "【输入框】"
        if label and isinstance(b, dict) and b:
            cx = (b.get("left", 0) + b.get("right", 0)) // 2
            cy = (b.get("top", 0) + b.get("bottom", 0)) // 2
            if not (drop_status_bar and cy < 110 and not clickable):
                out.append((len(out), cx, cy, label[:200], clickable))
        for c in node.get("children") or []:
            visit(c)

    visit(state.get("a11y_tree") or {})
    return out


APP_ANCHORS_FILE = os.path.expanduser("~/bridge/skills/app_anchors.json")
_APP_ANCHORS = [None]


def app_anchors(pkg):
    """按包名取"已知固定入口"坐标（归一化 0-1000）。

    为什么需要（2026-10-22 实测）：哔哩哔哩HD 的搜索栏是**自绘控件**，
    a11y 树里完全没有它（实测 82 个元素，只有 tab 和视频卡片）。
    任何"搜索"类任务都卡在"找不到搜索入口"上，模型只能瞎猜坐标。

    这类入口位置是**版本内稳定的**，记一次就能反复用 —— 存成锚点，
    注入成虚拟元素给模型（可 pick、可点），是"a11y 读不到"这一类问题的通用解。
    """
    global _APP_ANCHORS
    if _APP_ANCHORS[0] is None:
        try:
            with open(APP_ANCHORS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            _APP_ANCHORS[0] = d if isinstance(d, dict) else {}
        except Exception:
            _APP_ANCHORS[0] = {}
    return _APP_ANCHORS[0].get(pkg) or {}


def inject_anchor_elems(elems, pkg):
    """把已知锚点并入元素清单（虚拟元素，label 带【锚点】前缀）。"""
    try:
        anc = app_anchors(pkg)
        if not anc or not _SCREEN["w"] or not _SCREEN["h"]:
            return elems
        out = list(elems)
        n = len(out)
        for name, xy in anc.items():
            if not isinstance(xy, (list, tuple)) or len(xy) != 2:
                continue
            label = "【锚点】%s" % name
            if any(label in str(e[3]) for e in out):
                continue
            x = int(float(xy[0]) / 1000.0 * _SCREEN["w"])
            y = int(float(xy[1]) / 1000.0 * _SCREEN["h"])
            out.append((n, x, y, label, True))
            n += 1
        return out
    except Exception:
        return elems


def percept_coverage(elems):
    """感知覆盖度自检（2026-10-22 新增）。

    背景（酷安 T1 实测）：横屏下酷安是浮层/双栏布局，a11y 树只暴露其中一栏
    （实测 X 覆盖 658..1502 / 屏宽 2160 = 39%）。模型不知道自己在"半屏"，
    就拿记忆里的旧坐标往树外区域点 → 点空 → 反复重试。

    做法：把"可见范围只占屏幕多少"直接写进提示词，让模型知道边界。
    """
    try:
        if not elems or not _SCREEN["w"] or not _SCREEN["h"]:
            return ""
        xs = [e[1] for e in elems if isinstance(e[1], int)]
        ys = [e[2] for e in elems if isinstance(e[2], int)]
        if len(xs) < 4:
            return ""
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        SW, SH = _SCREEN["w"], _SCREEN["h"]
        cw = (x1 - x0) / float(SW)
        ch = (y1 - y0) / float(SH)
        parts = []
        if cw < 0.72:
            parts.append("横向只看到 x=%d..%d（约占屏宽 %.0f%%）" % (x0, x1, cw * 100))
        if ch < 0.55:
            parts.append("纵向只看到 y=%d..%d（约占屏高 %.0f%%）" % (y0, y1, ch * 100))
        if not parts:
            return ""
        return ("\n\n【感知边界·重要】%s。范围外的区域没有任何元素信息，"
                "禁止凭印象点那里的坐标（点空会浪费步数）；"
                "要操作范围外内容，先用返回键/滚动把目标移进可见范围。" % "；".join(parts))
    except Exception:
        return ""


def render_elems(elems):
    """补充后的元素清单（portal + 桥树）→ LLM 友好文本（qwen 与 jev 共用同一"事实来源"）。

    2026-10-12：**每行带编号 [N]**，让模型只报编号（`pick`）而不是抄坐标/猜名字 ——
    这是"一次成功率"最关键的一处：抄错坐标、名字对不上这两类失败从根上消失。"""
    lines = []
    for idx, x, y, label, clickable in elems:
        lines.append("[%d] (%d,%d) %s%s" % (idx, x, y, label, " 可点" if clickable else ""))
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


def jev_decide(task, elems, history, experience=None, related_apps=None, cur_pkg="",
                plan=None, goal_text=""):
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
    if goal_text:
        target_instr += ("\n" + goal_text +
                         "\n只专注完成「当前子目标」，不要跳步；当前子目标达成后再考虑下一个。")
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
        "任务类型 family 必须从这五个里选一个：\n"
        "  read=读数（读一个数值/结论）；list=列表（前N条/榜单/热搜/都有哪些）；"
        "search=搜索（要输入关键词去搜）；send=发送（给别人发消息，有副作用）；"
        "publish=发布（上传/发布内容，有副作用）。\n"
        "goals = 把任务拆成 2-4 个「必须逐个到达的中间目标」，每个目标给：\n"
        "  goal：一句话（做什么）；verify：到达该目标时屏幕上**一定会同时出现**的 1-2 个特征词"
        "（要稳定、不要用会变的内容）；fallback：没到达时换什么入口重来。\n"
        "steps = 把任务拆成**可直接执行的动作序列**（重点！系统会照它一次执行到底、逐步核对）：\n"
        "  每步 {\"do\": ..., \"target\": ..., \"verify\": [...], \"n\": ...}，do 只能是这五种：\n"
        "    open_app   —— 打开目标应用（不需要 target）\n"
        "    tap        —— 点击屏幕上**文字等于或包含 target 的元素**；target 必须是该 App 里"
        "真实存在的**短文字**（如「热榜」「市场情绪」「搜索」），不要写整句话、不要写坐标。"
        "**拿不准入口叫什么时，用 targets 给 2-4 个候选**（如 [\"热门\",\"排行榜\",\"热门榜\"]），任一命中即可\n"
        "    input_text —— 在输入框输入 value（一般先用 tap 点一下输入框）\n"
        "    scroll     —— 滚动，direction 填 down 或 up\n"
        "    read       —— 读答案：target=要读的元素文字；若是列表/榜单/前N条，额外给 n=条数\n"
        "  verify（可选）：到达该步后屏幕上**一定会出现**的 1-2 个稳定特征词（用于逐步核对，"
        "别用会变的内容）。**只有你很有把握时才给**；没把握就省略（系统会用包名等硬信号兜底核对）。\n"
        "  最后一步必须是 read（产出答案）。只写「做什么」，**绝对不要写坐标**（坐标由系统运行时按 target 文字自动定位）。\n"
        "请只输出一个 JSON（不要多余文字、不要 markdown）：\n"
        "{\"intent\": \"一句话说明用户想要什么（已纠正错别字）\", "
        "\"app_label\": \"完成任务最需要的应用名（必须来自上面清单；没有则 null）\", "
        "\"app_package\": \"对应包名（必须来自上面清单；没有则 null）\", "
        "\"family\": \"read|list|search|send|publish\", "
        "\"plan\": [\"第1步\", \"第2步\", \"第3步\", \"第4步\"], "
        "\"goals\": [{\"goal\": \"第1个中间目标\", \"verify\": [\"特征词1\", \"特征词2\"], "
        "\"fallback\": \"没到达时怎么做\"}], "
        "\"steps\": [{\"do\": \"open_app\"}, {\"do\": \"tap\", \"target\": \"热榜\", \"verify\": [\"热榜\"]}, "
        "{\"do\": \"read\", \"target\": \"热榜\", \"n\": 3}], "
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
    fam = str(d.get("family") or "").strip().lower()
    d["family"] = fam if fam in ("read", "list", "search", "send", "publish") else ""
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


def render_goals(goals, idx):
    """子目标块（关卡三）：当前目标 + 整体进度 + 本目标的到达标志。"""
    if not goals:
        return ""
    h = SL.goal_hint(goals, idx) if SL is not None else ""
    if not h:
        return ""
    cur = goals[idx] if 0 <= idx < len(goals) else {}
    ver = cur.get("verify") or {}
    words = []
    if isinstance(ver, dict):
        words = [str(t) for t in (ver.get("text") or []) if t]
    out = h
    if words:
        out += "｜到达标志：" + "、".join(words)
    if cur.get("fallback"):
        out += "｜没到达就改用：" + str(cur["fallback"])[:60]
    out += "｜整体进度：%d/%d 个目标已完成" % (idx, len(goals))
    return out


# ---------------------------------------------------------------- 调试 trace
class Tracer:
    """每任务一份 jsonl trace（prompt / reply / action / result），供调试浮窗与复盘。"""

    def __init__(self, path):
        self.path = path
        self.f = None
        self._t0 = time.time()
        self._steps = set()
        self._waste = {}
        self._llm = []
        self._pstart = None
        self._closed = False
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.f = open(path, "a", encoding="utf-8")
        except Exception:
            self.f = None

    # 浪费归因表（与 scripts/metrics.py 对齐）
    _WASTE_MAP = (("执行失败", "执行失败"), ("动作循环", "动作循环"),
                  ("重复动作", "重复动作"), ("屏幕无变化", "屏幕无变化"),
                  ("封禁", "坐标封禁"), ("BLOCK", "硬阻断"),
                  ("盲点点击", "盲点点击"), ("幂等跳过", "幂等跳过"))

    def log(self, step, kind, text, **extra):
        # —— 在线度量（2026-10-22）：任务结束要能直接报"几步/多久/浪费在哪" ——
        try:
            if step:
                self._steps.add(int(step))
            if kind == "prompt_start":
                self._pstart = time.time()
            elif kind == "reply" and self._pstart:
                self._llm.append(round(time.time() - self._pstart, 2))
                self._pstart = None
            elif kind == "result":
                _t = str(text or "")
                for pat, cat in self._WASTE_MAP:
                    if pat in _t:
                        self._waste[cat] = self._waste.get(cat, 0) + 1
        except Exception:
            pass
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
        if self.f and not self._closed:
            self._closed = True
            try:
                el = round(time.time() - self._t0, 1)
                summ = {"steps": len(self._steps), "elapsed": el,
                        "llm_calls": len(self._llm),
                        "llm_total": round(sum(self._llm), 1),
                        "llm_avg": round(sum(self._llm) / len(self._llm), 2) if self._llm else 0,
                        "waste": self._waste}
                self.f.write(json.dumps({"ts": round(time.time(), 2),
                                         "step": max(self._steps) if self._steps else 0,
                                         "kind": "summary",
                                         "text": json.dumps(summ, ensure_ascii=False)},
                                        ensure_ascii=False) + "\n")
                self.f.flush()
                print("[agent] 本次度量: %d 步 / %.1fs / 模型 %d 次共 %.1fs(均 %.2fs) / 浪费 %s"
                      % (summ["steps"], el, summ["llm_calls"], summ["llm_total"],
                         summ["llm_avg"],
                         ("、".join("%s×%d" % (k, v) for k, v in self._waste.items())
                          or "无")))
            except Exception:
                pass
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


def save_failure(task, reason, steps, stage="", pattern="", evidence=""):
    """任务失败时保存教训（按任务文本去重置顶，上限 30 条），下次同类任务注入"别再做"。
    2026-10-11：增加 stage（感知/规划/决策/执行/校验/锚点）与 pattern（错误签名）——
    这样"同一个错误反复出现"才能被统计出来，进而编译成硬闸门（guards.json）。"""
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
                        "stage": stage or "", "pattern": pattern or "",
                        "evidence": (evidence or "")[:160],
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
_BRIDGE_TO = [0]      # 桥连续超时计数（平板无 root：≥2 次 → 本进程熔断，不再白等）
_BRIDGE_DEAD = [False]


def bridge_cmd(cmd, timeout=8.0):
    """经 root 桥（xgt-bridge.sh）执行命令：返回 "ok" 或 "err:..."。
    协议：写 ~/bridge/.xgt_req（"<seq> <cmd>"）→ 桥执行 → 读 ~/bridge/.xgt_res。"""
    if _BRIDGE_DEAD[0]:
        return "err: bridge disabled"
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
                    _BRIDGE_TO[0] = 0
                    return (f.read() or "").strip()
            except OSError:
                time.sleep(0.05)
        _BRIDGE_TO[0] += 1
        if _BRIDGE_TO[0] >= 2:
            _BRIDGE_DEAD[0] = True
            print("[agent] root 桥连续 %d 次超时 → 熔断（无 root 设备走 portal/视觉通道）"
                  % _BRIDGE_TO[0])
        return "err: bridge timeout"
    except Exception as e:
        return "err: %r" % (e,)


def bridge_elements(timeout=8.0, dpy=0):
    """经 root 桥 + 小工头 App 取完整 a11y 树（含"不重要"视图，如微博信息流）。
    替代 uiautomator：实测 uiautomator dump 会触发系统解绑 portal 的 a11y 服务。
    dpy>0：只保留该显示屏（影子屏）窗口的元素（元素第 6 位 = displayId，App v1.1+ 提供）。"""
    out = os.path.expanduser("~/bridge/.tree.json")
    try:
        try:
            os.remove(out)
        except OSError:
            pass
        r = bridge_cmd("tree", timeout=timeout)
        if not r.startswith("ok"):
            if "disabled" not in r:          # 熔断后静默（避免每步刷屏）
                print("[agent] 桥取树失败: %s" % r)
            return []
        with open(out, encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        raw = []
        has_dpy = any(len(e) > 5 for e in (d.get("elems") or []))
        for e in d.get("elems") or []:
            try:
                d6 = int(e[5]) if len(e) > 5 else None
                if dpy > 0 and has_dpy and d6 != dpy:
                    continue
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


# ---------------------------------------------------------------- 微信发消息技能（T5：意图路由 → 预编译技能）
# 背景：微信 8.0.52+ 对第三方 a11y"根级过滤"读不到树，但"点"可用 →
#   用"唤醒屏→回列表→定位行→校验标题→点真键盘打字→校验输入→点发送→校验送达"的固定技能。
# 路由：任务文本命中"给X发Y"句式 → 直接调 ~/wx_send.py（0 模型 0 视觉 + 四道本地校验），
#   不进 Jev/qwen 慢循环；不命中则走原流程（对普通任务零影响）。
WX_SEND_ON = os.environ.get("WX_SEND_SKILL", "1") == "1"
WX_SEND_PY = os.path.expanduser(os.environ.get("WX_SEND_PY", "~/wx_send.py"))
_PY3 = os.environ.get("AGENT_PY3", "/data/data/com.termux/files/usr/bin/python3")


def parse_send_intent(task):
    """共享解析器（~/wx_intent.py，console 也用）。缺失则不做路由（安全退化）。"""
    try:
        import wx_intent
        return wx_intent.parse_send_intent(task)
    except Exception:
        return None


def wx_send_skill(to, text, tracer=None, timeout=150):
    """调手机本地发消息技能（agent 以 root 运行，直接子进程，无需 portal / 桥）。
    返回 (ok, message)；失败含具体阶段原因（零静默错误）。"""
    if not os.path.exists(WX_SEND_PY):
        return False, "技能未部署（%s 不存在）" % WX_SEND_PY
    outp = os.path.expanduser("~/bridge/.wx_last.json")
    try:
        os.remove(outp)
    except OSError:
        pass
    t0 = time.time()
    cmd = [_PY3, "-u", WX_SEND_PY, "--to", to, "--text", text, "--json-out", outp]
    print("[wxsend] exec: %s" % " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        try:   # 技能完整日志留档（排障用；out 尾部只打印不落盘会丢）
            with open(os.path.expanduser("~/bridge/.wx_last.log"), "w",
                      encoding="utf-8") as f:
                f.write("\n".join(out))
        except Exception:
            pass
        for ln in out[-16:]:
            print("[wxsend] " + ln)
        rc = r.returncode
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        if rc != 0 and err:
            for ln in err.splitlines()[-8:]:
                print("[wxsend][stderr] " + ln)
    except Exception as e:
        return False, "技能执行异常：%r" % (e,)
    detail = {}
    try:
        with open(outp, encoding="utf-8") as f:
            detail = json.load(f)
    except Exception:
        pass
    el = round(time.time() - t0, 1)
    if rc == 0 and detail.get("ok"):
        return True, "已给 %s 发送「%s」（%.1f 秒，四道校验通过）" % (to, text,
                                                              detail.get("elapsed", el))
    return False, "没有送达：%s（%.1f 秒，安全中止）" % (detail.get("reason") or "exit=%d" % rc, el)


# ---------------------------------------------------------------- 视觉兜底（a11y 树被屏蔽的 App，如微信 8.0.52+）
# 背景：微信 8.0.52+ 对非系统白名单的无障碍服务"根节点直接过滤"（实测 portal 报
#   "No active window or root filtered out"，树里只剩系统状态栏）→ 元素树感知彻底失效。
# 对策：截图（无 FLAG_SECURE，可用）→ 多模态模型给"文字+坐标" → 伪元素清单，下游零改动。
VISION_ON = os.environ.get("VISION_FALLBACK", "1") == "1"
_LAST_PKG = [""]   # 最近一次已知前台包名（portal 读不到时用于判断"是不是被屏蔽的 App"）
VISION_Q = ("这是安卓手机截图，分辨率 {w}x{h}（宽x高）。列出屏幕上所有可点击元素的中心坐标。"
            "只输出 JSON 数组，不要解释、不要代码块。"
            '每项形如 {{"label":"元素上的文字","x":X,"y":Y}}（X/Y 用 0-1000 归一化值）。最多 25 项。')

VISION_BUILTIN = {"com.tencent.mm"}
_VISION_APPS = None


def vision_apps():
    """需要用「截图+视觉」感知的 App = 内置 + ~/bridge/skills/vision_apps.json（list）。"""
    global _VISION_APPS
    if _VISION_APPS is None:
        _VISION_APPS = set(VISION_BUILTIN)
        try:
            with open(os.path.expanduser("~/bridge/skills/vision_apps.json"), encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, list):
                _VISION_APPS.update(str(x) for x in d)
        except Exception:
            pass
    return _VISION_APPS


def _png_size(png):
    """PNG 头读宽高（Termux 侧没装 PIL，手工解析 IHDR）。"""
    if len(png) >= 24 and png[:8] == b"\x89PNG\r\n\x1a\n":
        return (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big"))
    raise ValueError("not png")


# 2026-10-19 迭代1：真机屏幕尺寸自适应（平板横屏 2160x1350 与手机竖屏共用一套代码）
_SCREEN = {"w": 0, "h": 0}


def detect_screen_size(portal=None):
    """探测真机屏幕宽高：优先截图 PNG 头（天然跟随横竖屏），退化用元素最大边界，再退化 1080x2400。"""
    if _SCREEN["w"] and _SCREEN["h"]:
        return _SCREEN["w"], _SCREEN["h"]
    w = h = 0
    try:
        if portal is None:
            portal = Portal()
        png = portal.screenshot_png()
        if png:
            w, h = _png_size(png)
    except Exception:
        pass
    if not w or not h:
        try:
            root = (portal.get_state() or {}).get("a11y_tree") or {}

            def _mx(nd, key, best):
                b = nd.get("boundsInScreen") or {}
                v = b.get(key)
                if isinstance(v, int) and v > best:
                    best = v
                for c in nd.get("children") or []:
                    best = _mx(c, key, best)
                return best

            w = _mx(root, "right", 0)
            h = _mx(root, "bottom", 0)
        except Exception:
            pass
    if not w or not h:
        w, h = 1080, 2400
    _SCREEN["w"], _SCREEN["h"] = int(w), int(h)
    print("[agent] 屏幕尺寸: %dx%d（%s）" % (w, h, "横屏" if w > h else "竖屏"))
    return _SCREEN["w"], _SCREEN["h"]


def scroll_points(direction, zone=0):
    """scroll 动作 → 适配真机的滑动起止点。down=手指上滑（内容上移），up=手指下滑。
    zone: 0=屏幕中央 / 1=左 1/3 / 2=右 1/3（同一点滚动无效时自动换位，2026-10-19 迭代3）。"""
    w, h = _SCREEN["w"], _SCREEN["h"]
    if not w or not h:
        w, h = 1080, 2400
    zone_x = {0: 0.5, 1: 0.22, 2: 0.78}
    cx = int(w * zone_x.get(zone % 3, 0.5))
    if h > w:                                   # 竖屏手机
        y_hi, y_lo = int(h * 0.72), int(h * 0.30)
    else:                                       # 横屏平板：行程压短，避开贴边手势区
        y_hi, y_lo = int(h * 0.78), int(h * 0.24)
    if (direction or "down").lower() == "up":
        return (cx, y_lo, cx, y_hi, 500)
    return (cx, y_hi, cx, y_lo, 500)


def vision_elements(step=None, tracer=None):
    """截图 → 多模态模型 → 伪元素 [(idx,x,y,label,True)]；失败返回 []。

    坐标兼容两种模型输出：像素 或 0–1000 归一化（实测两种都出现，按"全 y ≤ 1000"判定）。
    延迟实测 ~12s/次（1080x2400），所以只在"树被屏蔽"的 App 上启用。
    """
    if not VISION_ON:
        return []
    try:
        png = Portal().screenshot_png()
        w, h = _png_size(png)
    except Exception as e:
        print("[agent] 视觉兜底：截图失败 %r" % (e,))
        return []
    b64 = base64.b64encode(png).decode()
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": VISION_Q.format(w=w, h=h)},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    ]}]
    try:
        txt = call_llm(msgs, timeout=150, max_tokens=2048)
    except Exception as e:
        print("[agent] 视觉兜底：模型调用失败 %r" % (e,))
        return []
    items = []
    m = re.search(r"\[[\s\S]*\]", txt or "")
    if m:
        try:
            items = json.loads(m.group(0))
        except Exception:
            try:
                items = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))
            except Exception:
                items = []
    ys = [it.get("y") for it in items if isinstance(it, dict) and isinstance(it.get("y"), (int, float))]
    if ys and max(ys) <= 1000 and h > 1200:   # 归一化坐标 → 像素
        for it in items:
            for k, dim in (("x", w), ("y", h)):
                v = it.get(k)
                if isinstance(v, (int, float)):
                    it[k] = int(round(v * dim / 1000.0))
    out = []
    for it in items[:25]:
        try:
            lb = str(it.get("label") or "").strip()
            x, y = int(it.get("x")), int(it.get("y"))
        except Exception:
            continue
        if lb and 0 <= x <= w and 0 <= y <= h:
            out.append((len(out), x, y, lb[:60], True))
    if out:
        print("[step %s] 视觉兜底：%d 个元素" % (step, len(out)))
        if tracer:
            tracer.log(step, "result", "视觉兜底 %d 元素（截图+多模态）" % len(out))
    return out


# ---------------------------------------------------------------- 影子屏（正式模式）直控
DISPLAY = 0   # >0 = 在影子屏上操作（正式模式；由 --display 参数设置）


def _clean_env():
    """剥离 Termux 的 LD_LIBRARY_PATH —— 否则系统二进制（input/am/dumpsys）会 CANNOT LINK。"""
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


def input_cmd(args, timeout=15):
    """root 直调 /system/bin/input（支持 -d N 指定显示屏）。失败抛异常。"""
    r = subprocess.run(["/system/bin/input"] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=timeout, env=_clean_env())
    if r.returncode != 0:
        raise RuntimeError("input rc=%d %s" % (r.returncode, (r.stderr or "").strip()[:120]))


def shadow_open_app(pkg, dpy, timeout=20):
    """在影子屏上启动应用：解析入口 Activity → am start --display N。返回 None=成功，否则错误文案。
    坑：**必须用 /system/bin/ 绝对路径** —— Termux 的 $PREFIX/bin 也有个 `am`（Termux:API 的），
    PATH 里排在最前会把系统的 am 顶掉（2026-09-27 实测踩坑：open_app 全部静默失败）。"""
    try:
        r = subprocess.run(["/system/bin/cmd", "package", "resolve-activity", "--brief", pkg],
                           capture_output=True, text=True, timeout=10, env=_clean_env())
        comp = ""
        for ln in reversed((r.stdout or "").strip().splitlines()):
            ln = ln.strip()
            if "/" in ln and " " not in ln:
                comp = ln
                break
        if not comp:
            return "无法解析入口 Activity：%s" % pkg
        r = subprocess.run(["/system/bin/am", "start", "--display", str(dpy), "-n", comp],
                           capture_output=True, text=True, timeout=timeout, env=_clean_env())
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode != 0 or "Error" in out:
            return out[:160] or ("am rc=%d" % r.returncode)
        return None
    except Exception as e:
        return "启动失败: %r" % (e,)


def display_focus_pkg(dpy, timeout=8):
    """影子屏当前前台应用包名（dumpsys window displays 按 Display 段解析）。"""
    try:
        r = subprocess.run(["/system/bin/dumpsys", "window", "displays"],
                           capture_output=True, text=True, timeout=timeout, env=_clean_env())
        cur = None
        for ln in (r.stdout or "").splitlines():
            m = re.search(r"Display: mDisplayId=(\d+)", ln)
            if m:
                cur = int(m.group(1))
                continue
            if cur == dpy:
                m2 = re.search(r"mFocusedApp=ActivityRecord\{[^}]*?\bu0\s+([A-Za-z0-9_\.]+)/", ln)
                if m2:
                    return m2.group(1)
    except Exception:
        pass
    return ""


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


def resolve_pick(elems, pick):
    """pick → (x, y, label)。**准确率关键**：让模型只报"第几号元素"，坐标由本地精确给出。

    接受三种写法：
      · 数字/数字串  → 元素清单里的**编号**（最准；模型不用抄坐标、不用猜名字）
      · 元素文本     → 精确相等优先，再前 6 字包含
      · None/空      → None
    """
    if pick is None or isinstance(pick, (list, dict)):
        return None
    s = str(pick).strip()
    if not s:
        return None
    if s.isdigit():
        i = int(s)
        for e in elems:
            if int(e[0]) == i:
                return int(e[1]), int(e[2]), str(e[3])
        return None
    for e in elems:
        if str(e[3]).strip() == s:
            return int(e[1]), int(e[2]), str(e[3])
    for e in elems:
        if len(s) >= 2 and s[:6] in str(e[3]):
            return int(e[1]), int(e[2]), str(e[3])
    return None


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
    "com.hexin.plat.android": {
        # 2026-10-19 平板实测：首次打开停在「登录流程指南」引导页（登录已有账户/基金开户），
        # 底部 Tab 在引导页下层点不动 → 直接按 BACK 退出引导页即达首页；上证指数在首页顶部。
        "hint": ("首次打开可能停在「登录流程指南」引导页（含「登录已有账户」「基金开户」等）——"
                 "这是引导页不是登录墙，点底部 Tab 无效，**按返回键(BACK)退出引导页**即达首页。"
                 "上证指数在首页顶部行情区（红色数字，如 3716.28）；看不到就向上滚动回顶部。"
                 "底部导航：首页 / 行情 / 交易 / 基金 / 我；查指数也可点「行情」tab。"),
        "spots": [],
    },
}
_APP_CARDS = None


def normalize_app_card(v):
    """统一 App 卡片格式（2026-10-11 起委托 scripts_lib，结构升级为
    {"hint","version","home_path","pages","spots"}；旧格式双向兼容）。"""
    if SL is not None:
        return SL.normalize_card(v)
    if isinstance(v, str):
        return {"hint": v, "version": 1, "home_path": None, "pages": [], "spots": []}
    if isinstance(v, dict):
        spots = []
        for s in (v.get("spots") or []):
            try:
                spots.append({"label": str(s[0]), "x": int(s[1]), "y": int(s[2]),
                              "whens": [str(w) for w in (s[3] if len(s) > 3 else [])],
                              "page": "", "hits": 0, "miss": 0, "last_ok": 0})
            except Exception:
                pass
        return {"hint": str(v.get("hint") or ""), "version": 1,
                "home_path": v.get("home_path") if isinstance(v.get("home_path"), dict) else None,
                "pages": [], "spots": spots}
    return {"hint": "", "version": 1, "home_path": None, "pages": [], "spots": []}


def app_cards():
    """App 经验卡 = 内置 APP_HINTS_BUILTIN + ~/bridge/skills/apps.json。
    外部 dict 采用**深合并**（只覆盖给了的字段：hint/home_path/pages/spots），
    外部 str 只覆盖 hint（保留内置坐标与页面定义）。"""
    global _APP_CARDS
    if _APP_CARDS is None:
        if SL is not None:
            _APP_CARDS = SL.cards_of(APP_HINTS_BUILTIN)
        else:
            cards = {str(k): normalize_app_card(v) for k, v in APP_HINTS_BUILTIN.items()}
            try:
                with open(os.path.expanduser("~/bridge/skills/apps.json"), encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    for k, v in d.items():
                        k = str(k)
                        old = cards.get(k)
                        if isinstance(v, dict):
                            nv = normalize_app_card(v)
                            if not old:
                                cards[k] = nv
                                continue
                            m = dict(old)
                            if nv.get("hint"):
                                m["hint"] = nv["hint"]
                            if nv.get("home_path"):
                                m["home_path"] = nv["home_path"]
                            if nv.get("pages"):
                                m["pages"] = nv["pages"]
                            if nv.get("spots"):
                                m["spots"] = nv["spots"]
                            cards[k] = m
                        else:
                            old = old or normalize_app_card("")
                            cards[k] = dict(old, hint=str(v))
            except Exception:
                pass
            _APP_CARDS = cards
    return _APP_CARDS


def app_hint_of(pkg):
    """当前 App 的文字要点（给 Jev/qwen 的提示词用）。"""
    c = app_cards().get(pkg or "")
    return (c or {}).get("hint") or ""


def app_coords(pkg, elems, cur_page="", dead=None):
    """App 经验坐标 → 可注入的虚拟元素。
    2026-10-11 升级：① 页面过滤（spot.page ≠ 当前页 → 不注入，治"错页误注入"）
                    ② 坐标自校验（同名真实元素已在屏上 → 不注入；坐标被占且历史命中率差 → 判失效）
                    ③ 本次运行失效名单 dead（点过没反应的坐标）
    委托 scripts_lib.app_coords2；SL 不可用时退回旧逻辑。"""
    if SL is not None:
        return SL.app_coords2(pkg, elems, cur_page, dead, app_cards())
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
    """从任务文本里找相关应用（label 子串匹配）。

    2026-10-22 修正（平板实测）：原逻辑"同 label 保留包名最短的"在 Pad 上是错的。
    案例：哔哩哔哩(task 里只写了这四个字)会命中 `tv.danmaku.bili`（手机版，**强制登录**），
    而真正该用的是 `tv.danmaku.bilibilihd`（HD 版，免登录可浏览）。
    修正：① 允许"同族变体"（label 以命中标签为前缀，如 哔哩哔哩HD ⊃ 哔哩哔哩）参与候选；
          ② 大屏/横屏设备上给 HD / Pad / 平板 变体加权，优先选它。
    """
    t = re.sub(r"\s+", "", task or "").lower()
    tablet = False
    try:
        tablet = bool(_SCREEN["w"]) and _SCREEN["w"] >= 1600 and _SCREEN["w"] >= _SCREEN["h"]
    except Exception:
        pass

    def hd_score(label, pkg):
        """越大越优先：HD/Pad 变体在平板上更合适。"""
        s = 0
        blob = (label + " " + pkg).lower()
        if any(k in blob for k in ("hd", "pad", "tablet", "平板")):
            s += 3 if tablet else 1
        return s

    hits = []
    for a in apps:
        label = str(a.get("label") or "").strip()
        pkg = str(a.get("packageName") or "")
        if not label or not pkg:
            continue
        lab = re.sub(r"\s+", "", label).lower()
        if len(lab) >= 2 and lab in t:
            hits.append((len(lab), len(pkg), label, pkg, hd_score(label, pkg), True))
            continue
        # 同族变体：任务里写的短名是本 label 的前缀（哔哩哔哩 ⊂ 哔哩哔哩hd）
        if len(lab) >= 4:
            for cut in range(len(lab) - 1, 3, -1):
                if lab[:cut] in t and lab[cut:] in ("hd", "pad", "平板", "hd版"):
                    hits.append((cut, len(pkg), label, pkg, hd_score(label, pkg), False))
                    break
    # 排序：变体优先度(-) > 标签吻合长度(-) > 包名长度(+)；再取前 limit
    hits.sort(key=lambda x: (-x[4], -x[0], x[1]))
    out, seen_pkg, seen_label = [], set(), set()
    for _, _, label, pkg, _s, _exact in hits:
        if pkg in seen_pkg or label in seen_label:
            continue
        seen_pkg.add(pkg)
        seen_label.add(label)
        out.append({"label": label, "package": pkg})
        if len(out) >= limit:
            break
    return out


# ================================================================ 确定性骨架 · 支撑（2026-10-11）
def get_activity():
    """当前前台 包名/Activity（2 秒缓存）。影子屏 / anchors 不可用 → ""。"""
    if not SW_ANCHORS or AN is None or DISPLAY > 0:
        return ""
    now = time.time()
    if _ACT_CACHE["v"] and now - _ACT_CACHE["ts"] < 2.0:
        return _ACT_CACHE["v"]
    v = ""
    try:
        v = AN.current_activity(0)
    except Exception:
        v = ""
    _ACT_CACHE.update({"ts": now, "v": v})
    return v


def get_fp():
    """当前屏标题墨迹指纹（3 秒缓存）。截图失败（FLAG_SECURE/影子屏）→ None。"""
    if not SW_ANCHORS or AN is None or DISPLAY > 0:
        return None
    now = time.time()
    if _FP_CACHE["v"] is not None and now - _FP_CACHE["ts"] < 3.0:
        return _FP_CACHE["v"]
    fp = None
    try:
        raw = AN.capture_raw(0)
        fp = AN.fingerprint(raw) if raw else None
    except Exception:
        fp = None
    _FP_CACHE.update({"ts": now, "v": fp})
    return fp


def _anchor_has_fp(a):
    return bool(isinstance(a, dict) and a.get("fingerprint"))


def _anchor_has_act(a):
    return bool(isinstance(a, dict) and a.get("activity"))


def verify_anchor(anchors, elems):
    """三级锚点验收。按需取 act/fp —— 锚点没用到就不付 dumpsys/screencap 的代价。"""
    if SL is None:
        return False
    act = get_activity() if _anchor_has_act(anchors) else ""
    fp = get_fp() if _anchor_has_fp(anchors) else None
    return SL.verify_anchors(anchors, elems, act, fp)


def page_of(pkg, elems):
    """当前页面身份（""=未知页）。"""
    if SL is None or not pkg:
        return ""
    cards = app_cards()
    card = cards.get(pkg) or {}
    act = get_activity() if any(pg.get("activity") for pg in (card.get("pages") or [])) else ""
    return SL.page_id(pkg, elems, act, None, cards)


def _do_action_simple(act, portal):
    """最小动作执行器（起点归位 / 脚本重放共用）。"""
    a = str(act.get("action") or "")
    if a == "key":
        portal.key(int(act.get("key_code", 4)))
        time.sleep(0.8)
    elif a == "tap":
        portal.tap(int(act["x"]), int(act["y"]))
        time.sleep(0.6)
    elif a == "swipe":
        portal.swipe(act.get("x1", 0), act.get("y1", 0), act.get("x2", 0),
                     act.get("y2", 0), act.get("duration", 500))
        time.sleep(0.6)
    elif a == "input_text":
        portal.input_text(str(act.get("text") or ""), bool(act.get("clear")))
        time.sleep(0.6)
    elif a == "open_app":
        portal.open_app(str(act.get("package") or ""))
        time.sleep(2.0)                                   # 冷启动初等（随后由"等到前台"兜）
    elif a == "wait":
        time.sleep(float(act.get("seconds") or 1.5))
    else:
        return False
    return True


def _script_elems(portal):
    """脚本重放用的轻量感知（portal → 桥树补盲）。返回 (elems, cur_pkg)。"""
    elems, cur = [], ""
    try:
        st = portal.get_state()
        elems = collect_elements(st)
        cur = (st.get("phone_state") or {}).get("packageName") or ""
    except Exception:
        elems = []
    try:
        if len(elems) < 8 or cur in blind_apps():
            ex = bridge_elements()
            if len(ex) > len(elems):
                elems = ex
    except Exception:
        pass
    return elems, cur


def _script_tap_spot(name, step, portal):
    """脚本 tap：**多候选 + 多策略**（精确 → 包含 → 前缀 → 滚动再找 → 卡片坐标）。

    2026-10-12 实证：模型/脚本给的 target 常与屏幕上文字对不上（B站要「热门」，屏幕上是
    「热门榜」；骨架第 2 步就因此断掉）。故支持候选列表 + 逐步放宽匹配 + 找不到就滚一次再找。"""
    step = step if isinstance(step, dict) else {}
    names = []
    tv = step.get("texts")
    if isinstance(tv, list):
        names = [str(x).strip() for x in tv if str(x).strip()]
    nm0 = str(name or "").strip()
    if nm0 and nm0 not in names:
        names.insert(0, nm0)

    def _scan(elems):
        for nm in names:                      # ① 精确相等
            for e in elems:
                if str(e[3]).strip() == nm:
                    return e
        for nm in names:                      # ② 候选是元素文字的子串
            if len(nm) < 2:
                continue
            for e in elems:
                if nm in str(e[3]):
                    return e
        for nm in names:                      # ③ 前 4 字前缀
            if len(nm) < 2:
                continue
            for e in elems:
                if nm[:4] in str(e[3]):
                    return e
        return None

    elems, _cur = _script_elems(portal)
    hit = _scan(elems)
    if hit is None and names:                 # ④ 滚动一次再找（元素可能在屏幕外）
        try:
            portal.swipe(540, 1700, 540, 700, 500)
            time.sleep(0.9)
            elems, _cur = _script_elems(portal)
            hit = _scan(elems)
        except Exception:
            pass
    if hit is not None:
        portal.tap(int(hit[1]), int(hit[2]))
        return True, ""
    xy = step.get("xy")
    if xy and len(xy) >= 2:
        portal.tap(int(xy[0]), int(xy[1]))
        return True, ""
    for nm in names:                          # ⑤ 卡片实测坐标
        key = nm[:4]
        if not key:
            continue
        for _pkg, card in app_cards().items():
            for sp in (card.get("spots") or []):
                lbl = str(sp.get("label") or "")
                if key and (lbl.startswith(key) or key in lbl):
                    portal.tap(int(sp["x"]), int(sp["y"]))
                    return True, ""
    return False, ("屏幕上与卡片里都找不到「%s」" % "/".join(names)) if names else "未指定 tap 目标"


def _script_rank(n, portal, rounds=4):
    """榜单提取：读当前屏 + 向下滚动收集（复用 extract_rank_pairs）。"""
    n = max(1, int(n))
    acc = {}
    for _ in range(max(1, int(rounds))):
        elems, _cur = _script_elems(portal)
        try:
            for score, title in extract_rank_pairs(elems):
                if title not in acc or acc[title] < score:
                    acc[title] = score
        except Exception:
            pass
        if len(acc) >= n + 2:
            break
        try:
            portal.swipe(540, 1700, 540, 700, 500)
        except Exception:
            break
        time.sleep(0.8)
    if len(acc) < n:
        return ""
    items = sorted(acc.items(), key=lambda kv: -kv[1])[:n]
    return "\n".join("%d. %s" % (i, t) for i, (t, _s) in enumerate(items, 1))


def _script_read_text(t, portal, dy=30):
    """读"含指定关键词的元素文本"。
    数值常被拆到相邻元素（如「实际涨停:」+「69家」、「07:00」+「法定工作日|起床闹铃」）
    → 当锚点文本**较短（≤12 字）**时，把同行邻近（|Δy| ≤ dy，|Δx| ≤ 420）的文本拼进来。
    长文本（如日历「已选中,10月11日,…没有日程」）直接原样返回，避免把整行日历拼成噪声。"""
    elems, _cur = _script_elems(portal)
    for e in elems:
        s = str(e[3]).strip()
        if not (t and t in s):
            continue
        if len(s) > 12:                       # 长文本已是完整答案 → 原样返回
            return s
        row = [(o[1], str(o[3]).strip()) for o in elems
               if abs(o[2] - e[2]) <= int(dy) and abs(o[1] - e[1]) <= 420
               and str(o[3]).strip()]
        row.sort()
        parts = []
        for _x, txt in row:
            if txt not in parts:
                parts.append(txt)
        return " ".join(parts) if parts else s
    return ""


# 挡路的一次性弹窗：判定**极严**（2026-10-11 血泪：早期版本把「已关闭」「所有闹钟已关闭」
# 这类**状态文字**、以及设置页的**蓝牙开关**（标签正好是「关闭」）当成弹窗按钮点了）。
# 规则：
#   · 有辨识度的多字短语（跳过/我知道了/以后再说…）→ 允许"包含"匹配，无位置限制
#   · 通用短词（关闭/取消/暂不/以后）→ 必须**完全相等**，且必须在屏幕**下半部**
#     （对话框的按钮通常在下方；设置页的开关/标签在上方）
DISMISS_EXACT_LOW = ("关闭", "取消", "暂不", "以后")
DISMISS_PHRASES = ("跳过", "以后再说", "稍后再说", "暂不更新", "不更新",
                   "下次再说", "我知道了", "知道了")

# 权限弹窗（2026-10-22 新增）：酷安实测会连续弹出「获取设备信息」「拨打电话」两个系统
# 权限框，模型看不懂就去点「允许」——既误授权又把任务带偏。
# 策略：只要能同时看到「允许」和一个拒绝类按钮，就确定地点击拒绝（不花 token、不误授权）。
PERM_ALLOW_HINTS = ("允许", "总是允许", "仅在使用中允许", "始终允许")
PERM_DENY_EXACT = ("拒绝", "不允许", "禁止", "暂不允许", "以后", "稍后", "取消",
                   "拒绝并退出", "暂不", "不许", "否")
PERM_DIALOG_HINTS = ("权限", "permission", "获取", "访问", "允许", "授权")


def _deny_permission_dialog(portal, elems, tracer=None):
    """自动拒绝系统/App 权限弹窗。返回点掉的个数（0/1）。

    判定条件（必须同时成立，避免误伤正常界面）：
      1. 存在标题类文本含「权限/授权/访问」字样
      2. 同时存在「允许」类按钮和「拒绝」类按钮
    """
    try:
        texts = [(e[3] or "").strip() for e in elems]
        joined = " ".join(texts)
        if not any(h in joined for h in PERM_DIALOG_HINTS):
            return 0
        has_allow = any(any(h in t for h in PERM_ALLOW_HINTS) and len(t) <= 10 for t in texts if t)
        if not has_allow:
            return 0
        hit = None
        for e in elems:
            if not e[4]:
                continue
            s = (e[3] or "").strip()
            if s in PERM_DENY_EXACT:
                hit = e
                break
        if not hit:
            return 0
        portal.tap(int(hit[1]), int(hit[2]))
        print("[agent] 权限弹窗 → 自动拒绝：%s (%d,%d)" % (hit[3], hit[1], hit[2]))
        if tracer:
            tracer.log(0, "result", "权限弹窗自动拒绝: %s" % hit[3])
        time.sleep(0.9)
        return 1
    except Exception:
        return 0


def _dismiss_popups(portal, elems, tracer=None, max_n=2):
    """点掉挡路的一次性弹窗（更新提示/广告/引导）。返回点掉的个数。"""
    n = 0
    try:
        h_est = max([e[2] for e in elems] or [2400]) or 2400
    except Exception:
        h_est = 2400
    y_low = int(h_est * 0.4)                     # 通用短词只认"下半屏"
    for _ in range(max(0, int(max_n))):
        hit = None
        for e in elems:
            if not e[4]:                          # 必须可点
                continue
            s = str(e[3]).strip()
            if not s or len(s) > 12:
                continue
            if any(w in s for w in DISMISS_PHRASES):
                hit = e
                break
            if s in DISMISS_EXACT_LOW and int(e[2]) >= y_low:
                hit = e
                break
        if not hit:
            break
        try:
            portal.tap(int(hit[1]), int(hit[2]))
            n += 1
            print("[agent] 关闭挡路弹窗：%s (%d,%d)" % (hit[3], hit[1], hit[2]))
            if tracer:
                tracer.log(0, "result", "关闭弹窗: %s" % hit[3])
            time.sleep(1.0)
        except Exception:
            break
        elems, _c = _script_elems(portal)
    return n


# 登录提示的"关闭类"文案（点它 = 先不看登录，继续用）
LOGIN_DISMISS = ("关闭", "以后再说", "稍后再", "暂不", "跳过", "取消", "我知道了", "知道了",
                 "不登录", "先逛逛", "随便看看", "游客", "×", "✕", "✗", "x")
ALERT_OGG = "/sdcard/xgt_alert.ogg"


def _dismiss_login(portal, elems, tracer=None):
    """关掉**登录提示**并继续任务（**不停止**）。

    2026-10-12 用户口径：很多 App 只是"弹一下"登录，关掉就能继续用；不该一看到登录页就停。
    返回 True = 做了关闭动作（调用方可重新感知后继续）。"""
    hit = None
    for e in elems:
        s = str(e[3]).strip()
        if not s or len(s) > 8:
            continue
        for w in LOGIN_DISMISS:
            if s == w or (len(w) >= 2 and w in s):
                hit = e
                break
        if hit:
            break
    if hit is not None:
        try:
            portal.tap(int(hit[1]), int(hit[2]))
            print("[agent] 关闭登录提示：%s (%d,%d)" % (hit[3], hit[1], hit[2]))
            if tracer:
                tracer.log(0, "result", "关闭登录提示: %s" % hit[3])
            time.sleep(1.0)
            return True
        except Exception:
            pass
    try:
        portal.key(4)                     # 没有关闭按钮 → 试一次返回键
        print("[agent] 登录提示无关闭按钮 → 按返回键尝试离开")
        time.sleep(0.8)
        return True
    except Exception:
        return False


def alert_user(title, text, tracer=None):
    """提醒用户（**通知 + 声音**），用于"真的需要登录"时叫人来处理。

    声音分层兜底（本机实测可用性）：
      ① 系统提示音文件 /product/media/audio/ui/*.ogg 用 am 播放（短促、明显）
      ② 再补一条通知横幅（即使没声音也能看到）
    注意：本机无 termux-api / 无 cmd vibrator，故走"am 播放系统提示音"这条路。"""
    ok_sound = False
    try:
        if not os.path.exists(ALERT_OGG):
            subprocess.run(["/system/bin/sh", "-c",
                            "cp /product/media/audio/ui/InCallNotification.ogg %s 2>/dev/null"
                            % ALERT_OGG], timeout=8)
        if os.path.exists(ALERT_OGG):
            subprocess.run(["/system/bin/am", "start", "-a", "android.intent.action.VIEW",
                            "-d", "file://" + ALERT_OGG, "-t", "audio/ogg"],
                           capture_output=True, timeout=10)
            ok_sound = True
    except Exception as e:
        print("[agent] 播放提示音失败: %r" % (e,))
    try:
        subprocess.run(["/system/bin/sh", "-c",
                        "cmd notification post -S bigtext -t '%s' xgt_alert '%s'"
                        % (str(title).replace("'", ""), str(text).replace("'", ""))],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    print("[agent] 已提醒用户：%s｜%s（声音=%s）" % (title, text, "已播放" if ok_sound else "未播放"))
    if tracer:
        tracer.log(0, "result", "提醒用户: %s" % text)


def _maybe_home_reset(pkg, elems, portal, tracer=None, done_set=None, target=None, fg_pkg=None):
    """关卡一 · 起点归位：目标 App 在前台但不在已知页（或落在死胡同页）→ 按卡片返航。
    返回 True=执行过归位。每个 App 每次运行最多归位一次（done_set 记账）。
    fg_pkg：当前真实前台包名 —— 与 pkg 不一致时**不归位**（防"App 还没起来就按返回键把它退掉"）。"""
    if not SW_HOME or SL is None or DISPLAY > 0 or not pkg:
        return False
    if done_set is not None and pkg in done_set:
        return False
    if fg_pkg and fg_pkg != pkg:
        print("[agent] 归位跳过：当前前台是 %s，不是目标 App %s" % (fg_pkg, pkg))
        return False
    cards = app_cards()
    card = cards.get(pkg) or {}
    if not card.get("home_path"):
        return False
    # 先点掉挡路的一次性弹窗 —— 否则"首页特征"被弹窗盖住，会被误判成"不在已知页"
    if _dismiss_popups(portal, elems, tracer):
        elems, _c = _script_elems(portal)
    act = get_activity() if any(pg.get("activity") for pg in (card.get("pages") or [])) else ""
    if not SL.need_home(pkg, elems, act, None, cards, target=target):
        return False
    steps = SL.home_steps(card)
    if not steps:
        return False
    if done_set is not None:
        done_set.add(pkg)
    print("[agent] 起点归位：%s 当前不在已知页 → 执行 %d 步返航" % (pkg, len(steps)))
    if tracer:
        tracer.log(0, "result", "起点归位 %s（%d 步）" % (pkg, len(steps)))
    until = SL.home_until(card)
    ok = False
    # 逐步执行 + 每步验收：达标即停（多余的 BACK 会把 App 退到桌面）
    for a in steps:
        try:
            _do_action_simple(a, portal)
        except Exception:
            pass
        el2, _c2 = _script_elems(portal)
        if until and any(w in "|".join(str(e[3]) for e in el2) for w in until):
            ok = True
            break
        if _c2 and _c2 != pkg:
            print("[agent] 归位中止：已离开 %s（当前 %s）→ 重新打开该 App 兜底" % (pkg, _c2))
            try:
                portal.open_app(pkg)
                time.sleep(2.0)
            except Exception:
                pass
            break
    if not ok:
        for _ in range(3):                       # 页面可能还在渲染，补一轮等待
            time.sleep(1.0)
            el2, _c2 = _script_elems(portal)
            if until and any(w in "|".join(str(e[3]) for e in el2) for w in until):
                ok = True
                break
    print("[agent] 归位%s" % ("成功（已回到已知页）" if ok else "未确认（继续任务）"))
    if tracer:
        tracer.log(0, "result", "归位%s" % ("成功" if ok else "未确认"))
    return True


def _sys_truth(task):
    """**系统实测真值**：能用系统 API 直读的，就别让模型"看图猜"（2026-10-12 新增）。

    场景：任务问"现在连的 WiFi 叫什么"，模型在设置页读到"未发现可用网络"就作答 ——
    而 `dumpsys wifi` 明明写着 SSID=Xiaomi_3ADA。用系统真值交叉核对，能直接拦下这类错答。
    返回 {"wifi": ssid, "battery": "68"}（取不到就不放键）。"""
    out = {}
    t = str(task or "")

    def _env():
        e = dict(os.environ)
        e.pop("LD_LIBRARY_PATH", None)
        e.pop("LD_PRELOAD", None)
        return e
    try:
        if any(w in t for w in ("wifi", "WIFI", "WiFi", "无线", "WLAN", "wlan", "局域网")):
            r = subprocess.run(["/system/bin/dumpsys", "wifi"], capture_output=True, text=True,
                               timeout=10, env=_env())
            m = re.search(r'mWifiInfo SSID: "([^"]*)"', r.stdout or "")
            if m and m.group(1) and m.group(1) != "<unknown ssid>":
                out["wifi"] = m.group(1)
    except Exception:
        pass
    try:
        if any(w in t for w in ("电量", "电池")):
            r = subprocess.run(["/system/bin/dumpsys", "battery"], capture_output=True, text=True,
                               timeout=8, env=_env())
            m = re.search(r"^\s*level:\s*(\d+)", r.stdout or "", re.M)
            if m:
                out["battery"] = m.group(1)
    except Exception:
        pass
    return out


def _finalize_answer(task, plan, family, answer, source, tracer=None):
    """关卡四 · 收工结果复核（规则优先，0 模型调用）。

    用户要求「每个步骤都必须是正确的，防止莫名其妙的错误」：
      过程正确 → 每步三级锚点（本地）
      答案正确 → 本函数（本地规则）
    规则只做高置信度判定，不确定时放行。返回 (ok, reason)；ok=False → 调用方应视为失败。
    """
    if not SW_REVIEW or SL is None:
        return True, ""
    try:
        ok, why = SL.review_answer(task, answer, plan, family)
    except Exception as e:
        print("[agent] 结果复核异常（放行）: %r" % (e,))
        return True, ""
    if ok:
        print("[agent] 结果复核通过（%s）" % source)
    else:
        print("[agent] 结果复核未过（%s）：%s" % (source, why))
        if tracer:
            tracer.log(0, "result", "结果复核未过(%s): %s" % (source, why))
    return ok, why


def replay_script(sc, tracer=None):
    """关卡二 · 脚本重放。返回 (ok, result, log, broken_at)。"""
    if SL is None:
        return False, "", ["scripts_lib 不可用"], 0
    p = Portal()

    def _do(act):
        try:
            return (True, "") if _do_action_simple(act, p) else \
                   (False, "动作不支持：%s" % act.get("action"))
        except Exception as e:
            return False, repr(e)

    def _after_step(i, st):
        # open_app 之后：① 先等 App 真正到前台（冷启动最长约 8 秒）
        #               ② 若落在未知/死胡同页 → 按卡片返航（治"App 恢复上次页面"）
        if str(st.get("do") or "") != "open_app":
            return
        pkg = str(st.get("package") or sc.get("app") or "")
        if not pkg:
            return
        # 等「到前台」+「界面加载稳定」+「页面身份可识别」（三条件齐了才动手）
        #   2026-10-11 血泪：只等"元素数稳定"不够——开盘啦冷启动时会先渲染出 10 个元素
        #   （顶栏+底栏，没有首页图标），数量稳定但内容没出来 → 脚本第 1 步误判失败。
        el, fg, prev, stable = [], "", -1, 0
        for _ in range(14):
            el, fg = _script_elems(p)
            try:
                _pg = page_of(pkg, el) if fg == pkg else ""
            except Exception:
                _pg = ""
            if fg == pkg and len(el) >= 8 and _pg and len(el) == prev:
                break
            prev = len(el)
            time.sleep(1.0)
        if fg and fg != pkg:
            print("[script] 等待 %s 到前台超时（当前 %s）" % (pkg, fg))
            return
        if _dismiss_popups(p, el, tracer):
            time.sleep(1.0)
            el, _fg2 = _script_elems(p)
        # 脚本重放：必须在"入口页"起步 —— 不在就先归位（治"App 恢复上次的详情页"）
        _tgt = None
        try:
            if SL is not None:
                _tgt = SL.entry_pages(app_cards().get(pkg) or {}) or None
        except Exception:
            _tgt = None
        _maybe_home_reset(pkg, el, p, tracer, done_set=_HOME_DONE, fg_pkg=fg or pkg, target=_tgt)

    ctx = {
        "get_elems": lambda: _script_elems(p)[0],
        "get_activity": lambda: get_activity(),
        "get_fp": lambda: get_fp(),
        "do_action": _do,
        "tap_spot": lambda name, step: _script_tap_spot(name, step, p),
        "extract_rank": lambda n: _script_rank(n, p),
        "read_text": lambda t, st: _script_read_text(
            t, p, dy=int((st or {}).get("dy") or 30)),
        "after_step": _after_step,
        "log": (lambda s: tracer.log(0, "result", "script: " + s)) if tracer else None,
    }
    return SL.replay(sc, ctx)


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


_JEV_OFF_FILE = os.path.expanduser("~/bridge/.jev_disabled")


def _jev_off():
    """jev 服务端已判死（451 等）→ 文件缓存，跨 run 不再重试（2026-10-19 迭代5）。"""
    return os.path.exists(_JEV_OFF_FILE)


def decide(step, task, state, history, engine_now, elems, experience=None, related_apps=None,
           plan=None, goal_text=""):
    """返回 (act, engine_name, seconds, trace_info)。trace_info = {"prompt":..., "reply":...}"""
    t0 = time.time()
    if engine_now == "jev" and (_JEV_FAILS[0] >= 2 or _jev_off()):
        # jev 连续失败（如 451 / 连不上）→ 本次运行不再尝试，直接走 qwen（省一次无效往返/步）
        pass
    elif engine_now == "jev":
        try:
            cur_pkg = ""
            try:
                cur_pkg = (state.get("phone_state") or {}).get("packageName") or ""
            except Exception:
                pass
            answers = jev_decide(task, elems, history, experience, related_apps, cur_pkg,
                                 plan, goal_text)
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
            _JEV_FAILS[0] = 0
            return act, "jev", time.time() - t0, ti
        except Exception as e:
            _JEV_FAILS[0] += 1
            if "451" in repr(e):
                try:
                    with open(_JEV_OFF_FILE, "w", encoding="utf-8") as f:
                        f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " 451 Unavailable\n")
                    print("[agent] jev 返回 451 → 已写入 %s，此后所有运行跳过 jev" % _JEV_OFF_FILE)
                except OSError:
                    pass
            print("[step %d] jev failed: %r -> qwen fallback（连续失败 %d 次%s）"
                  % (step, e, _JEV_FAILS[0],
                     "，本次运行起不再尝试 jev" if _JEV_FAILS[0] == 2 else ""))
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
    goal_block = ("\n\n" + goal_text +
                  "\n（只专注完成「当前子目标」；它达成后再推进下一个。全部子目标达成即可 done。）") \
        if goal_text else ""
    # 当前页面身份（2026-10-12）：模型常因"两个页共用同一 Activity"而误判自己在哪 ——
    # 把 App/页面名明确告诉它，能显著减少"以为在首页其实在子页"这类错误。
    page_note = ""
    try:
        _pk2 = (state.get("phone_state") or {}).get("packageName") or ""
        if _pk2:
            _pg = page_of(_pk2, elems)
            page_note = "\n\n【当前页面】%s%s" % (_pk2, ("｜%s" % _pg) if _pg else "（未登记页面）")
    except Exception:
        page_note = ""
    screen_size_note = ""
    try:
        if _SCREEN["w"] and _SCREEN["h"]:
            screen_size_note = ("\n\n【屏幕】%dx%d（%s）。坐标按此屏幕真实像素。"
                                % (_SCREEN["w"], _SCREEN["h"],
                                   "横屏" if _SCREEN["w"] > _SCREEN["h"] else "竖屏"))
    except Exception:
        pass
    coverage_note = percept_coverage(elems)
    # —— 输入状态提示（2026-10-22 新增）——
    #    实测（B站HD 搜索页）：键盘已弹出、光标已在输入框内，模型却坚持"再点一次搜索框确保聚焦"，
    #    连点 6 次被判无效。原因是没人告诉它"现在可以直接打字"。
    input_note = ""
    try:
        _ps = (state.get("phone_state") or {})
        _kb = bool(_ps.get("keyboardVisible"))
        _ed = bool(_ps.get("isEditable"))
        _fe = _ps.get("focusedElement") or {}
        _fe_hint = ""
        try:
            if isinstance(_fe, dict):
                _fe_hint = str(_fe.get("text") or _fe.get("className") or "")[:30]
        except Exception:
            _fe_hint = ""
        if _kb:
            input_note = ("\n\n【输入状态·重要】软键盘已弹出，光标已经在输入框里%s。"
                          "**不要再点输入框了**，直接输出 "
                          "{\"action\":\"input_text\",\"text\":\"要输入的内容\"}；"
                          "输入完成后用 {\"action\":\"key\",\"key_code\":66}（回车）提交搜索。"
                          % (("（%s）" % _fe_hint) if _fe_hint else ""))
        elif _ed:
            input_note = ("\n\n【输入状态】当前有可编辑输入框但键盘未弹出，"
                          "先 tap 那个【输入框】元素，再 input_text。")
    except Exception:
        input_note = ""
    user = ("任务: %s%s%s%s\n\n第 %d 步。当前屏幕元素清单（[编号] 坐标 文本）：\n%s%s%s%s%s%s%s\n\n"
            "请输出下一步动作 JSON（点元素优先用 pick 报编号）。"
            % (task, plan_block, goal_block, page_note, step, screen,
               exp_block, app_hint, app_note, screen_size_note, coverage_note, input_note))
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history[-10:] + \
               [{"role": "user", "content": user}]
    reply = call_llm(messages)
    return parse_action(reply), "qwen", time.time() - t0, {"prompt": user, "reply": reply}


def parse_args():
    argv = sys.argv[1:]
    kv = {}
    positional = []
    flags = {"--max-steps", "--engine", "--upgrade-after", "--display"}
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
        max_steps = int(kv.get("--max-steps") or os.environ.get("MAX_STEPS", "100"))
    except ValueError:
        max_steps = 100
    try:
        upgrade_after = int(kv.get("--upgrade-after") or os.environ.get("UPGRADE_AFTER", "3"))
    except ValueError:
        upgrade_after = 3
    try:
        display = int(kv.get("--display") or os.environ.get("AGENT_DISPLAY", "0"))
    except ValueError:
        display = 0
    return task, max_steps, mode, upgrade_after, display


def main():
    global DISPLAY
    os.makedirs(OUT_DIR, exist_ok=True)
    task, max_steps, mode, upgrade_after, display = parse_args()
    DISPLAY = display
    if DISPLAY > 0:
        print("[agent] 正式模式：全部操作在影子屏 display=%d 上执行" % DISPLAY)

    # —— 意图路由：微信发消息技能（0 模型 0 视觉；不命中则走原流程。影子屏模式不路由） ——
    if WX_SEND_ON and DISPLAY == 0:
        intent = parse_send_intent(task)
        if intent:
            to, text = intent
            # 代词护栏（语音口误常见）："给那个发…"→ 无法确定对象 → 安全停，
            # 绝不拿代词去列表里"找最像的"（防认错人）。
            try:
                import wx_intent as _wi
                _is_pro = getattr(_wi, "is_pronoun", None)
            except Exception:
                _is_pro = None
            if _is_pro and _is_pro(to):
                msg = ("没听清要发给谁（听到的是「%s」）——请说清名字，"
                       "比如「给浩浩发 test」。这条没有执行任何操作。" % to)
                print("[agent] 意图路由命中，但收件人是代词「%s」→ 安全停（0 点击 0 输入）" % to)
                tr = Tracer(TRACE_PATH or os.path.join(OUT_DIR, "agent_trace.jsonl"))
                tr.log(0, "result", msg)
                print("[agent] FAILED: %s" % msg)
                tr.close()
                return 3
            tr = Tracer(TRACE_PATH or os.path.join(OUT_DIR, "agent_trace.jsonl"))
            print("[agent] 意图路由 → 微信发消息技能：给 %s 发「%s」（0 模型 0 视觉）" % (to, text))
            tr.log(0, "action", "wxsend to=%s text=%s" % (to, text))
            ok, msg = wx_send_skill(to, text, tr)
            if ok:
                print("[agent] DONE: %s" % msg)
                tr.log(1, "done", msg)
            else:
                print("[agent] FAILED: %s" % msg)
                tr.log(1, "result", msg)
            tr.close()
            return 0 if ok else 3

    portal = Portal()
    history = []
    trace_path = TRACE_PATH or os.path.join(OUT_DIR, "agent_trace.jsonl")
    tracer = Tracer(trace_path)
    usage = {"jev": 0, "qwen": 0}
    # auto 模式尊重 jev 缓存（451 判死则直接 qwen 起步）；显式指定模式仍按用户所选
    engine_now = ("qwen" if mode == "qwen" else
                  ("jev" if not _jev_off() else "qwen"))
    prog = Progress()
    aborted = False
    result = ""        # 中止原因（熄屏自救失败等会写入；提前初始化防止 UnboundLocalError）
    exec_log = []
    fail_counts = {}   # 动作签名 -> 连续失败次数（>=2 硬阻断）
    no_effect = {}     # tap 签名 -> 连续"屏幕无变化"次数（>=2 视为无效点击）
    blind_taps = [0]   # 盲点点击计数（坐标附近无任何元素）
    fg_miss = [0]      # 目标 App 连续不在前台的步数（>=2 触发确定性拉起）
    last_sig, last_ok, last_hash = None, None, None
    last_pick = ""     # 上一步 tap 的目标文字（用于标记失效的经验坐标）
    block_streak = 0   # 连续被系统拒绝的次数
    done_rejects = 0   # done 被防幻觉复核驳回的次数（上限 2）
    scroll_streak = 0  # 连续滚动/滑动次数（迷路检测：≥6 次强制升级）
    scroll_osc = [0]     # 滚动方向来回切换次数（下↔上震荡检测）
    scroll_last_dir = [""]  # 上一次滚动方向
    back_up = [0]        # 榜单就绪后允许向上滚回顶部的次数
    _rn_global = [0]     # 任务要的条数 N（供滚动闸门使用）
    scroll_zone = [0]  # 滚动无效自动换位（2026-10-19 迭代3）：0中央/1左/2右
    prev_hash = None   # 上上步屏幕指纹（判断"连续两次滚动屏幕没变"）
    last_sw_sig, sw_repeat = None, 0  # 连续相同滑动检测（≥3 软提醒，≥7 硬阻断）
    login_warned = False  # 登录页提示只发一次
    rank_acc = {}      # 榜单跨步累积：title -> 最高热度（滚动收集"第N条"类任务用）
    rank_ready = False       # 榜单收集足够（已提示可直接作答）
    rank_collect_hint = False  # 榜单收集催促（只发一次）
    kb_switched = False        # 键盘弹出已触发 qwen 接管（只触发一次）
    tap_seen = {}              # tap 坐标签名 -> 累计次数（≥4 → 封禁该坐标）
    goal_hinted = set()        # 已发过软提示的子目标（同一目标只提示一次，避免刷屏干扰）
    max_block_streak = 0       # 本次运行的最大连败（供失败归类 / 脚本固化判定）
    min_elems_seen = 999       # 本次运行见过的最少元素数（感知是否失效）
    anchor_miss = 0            # 页面身份未命中次数（锚点是否够硬）
    lock_strikes = 0           # 熄屏/锁屏连续命中（迭代5：≥2 判死，烧预算前 fail-fast）
    errs = []                  # 执行错误文案（供失败归类）

    print("[agent] task: %s" % task)
    try:
        detect_screen_size(portal)          # 2026-10-19 迭代1：开跑先量屏幕
    except Exception:
        pass
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
        # —— 平板变体纠正（2026-10-22 实测驱动）——
        #    规划器是独立 LLM 调用，仍会挑手机版（如 tv.danmaku.bili 强制登录），
        #    而当前设备上存在 HD/Pad 变体（tv.danmaku.bilibilihd 免登录可浏览）。
        #    这里做一次确定性纠正：若 plan 选中的包名有 HD/Pad 同族变体，改用它。
        try:
            _pp = str(plan.get("app_package") or "")
            if _pp:
                _sib = [ra for ra in related_apps
                        if ra.get("package") != _pp
                        and any(k in (str(ra.get("package", "")) + str(ra.get("label", ""))).lower()
                                for k in ("hd", "pad", "tablet", "平板"))]
                _is_tab = bool(_SCREEN["w"]) and _SCREEN["w"] >= 1600 and _SCREEN["w"] >= _SCREEN["h"]
                _cur_hd = any(k in _pp.lower() for k in ("hd", "pad", "tablet"))
                if _sib and _is_tab and not _cur_hd:
                    _new = _sib[0]
                    print("[agent] 平板变体纠正: %s(%s) → %s(%s)"
                          % (plan.get("app_label"), _pp, _new.get("label"), _new.get("package")))
                    tracer.log(0, "result", "平板变体纠正 %s→%s" % (_pp, _new.get("package")))
                    plan["app_package"] = _new.get("package")
                    plan["app_label"] = _new.get("label")
        except Exception as _e_corr:
            print("[agent] 平板变体纠正异常（跳过）: %r" % (_e_corr,))
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

    # ================================ 关卡〇 · 开工闸门（可行性 + 分级预算）—— 2026-10-11
    family = ""
    if SW_FAMILY and SL is not None:
        try:
            family = SL.match_family(plan, task)
        except Exception:
            family = ""
    if family:
        try:
            print("[agent] 任务家族: %s（%s，预算 %d 步）"
                  % (family, (SL.load_families().get(family) or {}).get("name", ""),
                     SL.budget_of(family)))
        except Exception:
            print("[agent] 任务家族: %s" % family)
    if SW_BUDGET and SL is not None and family:
        try:
            _bud = SL.budget_of(family)
            # —— 预算按"要收集的条数"缩放（2026-10-22 实测驱动）——
            #    微博热搜「前10条」任务只给 30 步，模型已成功打开榜单页，
            #    却在滚动收集第 9~10 条时步数耗尽 → 白跑。
            #    规则：list/read 家族每多要 1 条，多给 3 步（列表每屏约 6~8 条，需滚动）。
            try:
                _rn_b = parse_rank_n(task) or parse_rank_n((plan or {}).get("intent") or "")
                if _rn_b and _rn_b > 3 and family in ("list", "read"):
                    _extra = (_rn_b - 3) * 3
                    _bud = (_bud or 30) + _extra
                    print("[agent] 预算按条数缩放：要 %d 条 → +%d 步" % (_rn_b, _extra))
            except Exception:
                pass
            if _bud and _bud < max_steps:
                print("[agent] 预算收紧: %d → %d 步" % (max_steps, _bud))
                max_steps = _bud
            # 步数放宽后时长要同步放宽，否则会先撞 300s 墙（每步约 3~5 秒）
            try:
                global TIME_CAP
                _need_t = max_steps * 8.0
                if TIME_CAP and _need_t > TIME_CAP:
                    print("[agent] 时长上限同步放宽: %.0fs → %.0fs" % (TIME_CAP, _need_t))
                    TIME_CAP = _need_t
            except Exception:
                pass
        except Exception:
            pass

    _gate_elems, _gate_pkg = [], ""
    if SW_GATE and SL is not None:
        try:
            _stg = portal.get_state()
            _gate_elems = collect_elements(_stg)
            _gate_pkg = (_stg.get("phone_state") or {}).get("packageName") or ""
        except Exception:
            _gate_elems = []
        try:
            _ok_fe, _why_fe, _kind_fe = SL.feasibility_check(plan, apps, task, family, _gate_elems)
            if not _ok_fe:
                _m = "无法完成：%s" % _why_fe
                print("[agent] 开工闸门拦下（%s）：%s" % (_kind_fe, _why_fe))
                tracer.log(0, "result", "开工闸门(%s): %s" % (_kind_fe, _why_fe))
                print("[agent] DONE: %s" % _m)
                tracer.log(1, "done", _m)
                tracer.close()
                return 0
        except Exception as e:
            print("[agent] 开工闸门异常（跳过）: %r" % (e,))

    # ================================ 关卡二 · 脚本重放（命中则 0 决策直跑；失败自动降级）
    _sc_hit = False
    if SW_SCRIPT and SL is not None and DISPLAY == 0:
        try:
            _sc = SL.match_script(task, family, _gate_pkg, apps)
            if _sc:
                _sc_hit = True
                print("[agent] 命中脚本「%s」（family=%s，历史 %s/%s）→ 重放"
                      % (_sc.get("name"), _sc.get("family"),
                         _sc.get("ok") or 0, _sc.get("runs") or 0))
                tracer.log(0, "action", "script replay: %s" % _sc.get("id"))
                _ok0, _res0, _lg0, _brk0 = replay_script(_sc, tracer)
                for _l in _lg0:
                    print("[script] " + _l)
                try:
                    SL.promote_candidate(_sc.get("id"), _ok0)
                except Exception:
                    pass
                if _ok0 and _res0:                 # 必须有实际答案才算成功（防"假完成"）
                    _rv_ok, _rv_why = _finalize_answer(task, plan, family, _res0, "脚本重放", tracer)
                    if _rv_ok:
                        print("[agent] engine-usage: jev=0 qwen=0（脚本重放）")
                        print("[agent] DONE: %s" % _res0)
                        tracer.log(1, "done", _res0)
                        tracer.close()
                        return 0
                    # 结果复核未过 → 不认这个答案，降级自由循环重新确认
                    SCRIPT_BREAK_HINT[0] = (
                        "（系统）已按「%s」的既定路径跑到一个答案，但**结果复核未通过**（%s）。"
                        "那个答案是：%s。请从当前屏幕重新确认，给出正确答案；"
                        "不要直接照抄上面的答案。" % (_sc.get("name"), _rv_why, _res0[:80]))
                    _ok0, _brk0 = False, len(_sc.get("steps") or [])
                if _ok0 and not _res0:
                    print("[agent] 脚本跑完但没产出答案 → 视为失败，降级自由循环")
                    _ok0, _brk0 = False, 0
                _steps0 = _sc.get("steps") or []
                _exp0 = ""
                if 1 <= _brk0 <= len(_steps0):
                    _exp0 = json.dumps((_steps0[_brk0 - 1] or {}).get("verify") or {},
                                       ensure_ascii=False)[:80]
                print("[agent] 脚本断裂于第 %d 步 → 降级自由循环" % _brk0)
                tracer.log(0, "result", "脚本断裂于第 %d 步（期望 %s）→ 降级" % (_brk0, _exp0))
                SCRIPT_BREAK_HINT[0] = (
                    "（系统）已按「%s」的既定路径尝试过，在第 %d 步失败（期望看到 %s）。"
                    "请从当前屏幕接管，不要重复脚本已失败的动作。" % (_sc.get("name"), _brk0, _exp0))
        except Exception as e:
            print("[agent] 脚本重放异常（跳过）: %r" % (e,))

    # ================================ 关卡二' · 规划骨架确定性执行（三段式核心）
    #   用户约束（2026-10-12）：模型不常驻、不牺牲速度、每步必须正确。
    #   故：规划期**一次**产出声明式骨架（按元素名，不写坐标）→ 执行期逐条"解析坐标 +
    #   执行 + 三级锚点核对"（**0 模型**）→ 某步核对失败 → 交回模型做局部恢复。
    #   仅在"没命中已固化脚本"时才走这条（已固化脚本是验证过的路径，优先级更高）。
    if (SW_SKELETON and SL is not None and DISPLAY == 0 and plan and not _sc_hit):
        try:
            _sk = SL.compile_plan_steps(plan, plan.get("app_package") or "")
            if _sk:
                _sksc = {"id": "plan-skeleton", "app": plan.get("app_package") or "",
                         "name": (plan.get("intent") or task)[:30], "steps": _sk}
                print("[agent] 规划骨架 %d 步 → 确定性执行（0 每步模型）" % len(_sk))
                tracer.log(0, "action", "plan-skeleton: "
                           + json.dumps(_sk, ensure_ascii=False)[:500])
                _ok1, _res1, _lg1, _brk1 = replay_script(_sksc, tracer)
                for _l in _lg1:
                    print("[skeleton] " + _l)
                if _ok1 and _res1:
                    _rv_ok, _rv_why = _finalize_answer(task, plan, family, _res1,
                                                       "规划骨架", tracer)
                    if _rv_ok:
                        print("[agent] engine-usage: jev=0 qwen=0（规划骨架执行）")
                        print("[agent] DONE: %s" % _res1)
                        tracer.log(1, "done", _res1)
                        tracer.close()
                        return 0
                    SCRIPT_BREAK_HINT[0] = (
                        "（系统）已按规划骨架跑到一个答案，但**结果复核未通过**（%s）。"
                        "那个答案是：%s。请从当前屏幕重新确认并给出正确答案。"
                        % (_rv_why, _res1[:80]))
                else:
                    _steps1 = _sk
                    _exp1 = ""
                    if 1 <= _brk1 <= len(_steps1):
                        _exp1 = json.dumps((_steps1[_brk1 - 1] or {}).get("verify") or {},
                                           ensure_ascii=False)[:80]
                    print("[agent] 规划骨架断裂于第 %d 步 → 交回模型恢复" % _brk1)
                    tracer.log(0, "result", "骨架断裂于第 %d 步（期望 %s）→ 交回模型"
                               % (_brk1, _exp1))
                    SCRIPT_BREAK_HINT[0] = (
                        "（系统）已按规划骨架执行到第 %d 步，核对未通过（期望屏幕上出现 %s）。"
                        "骨架原计划：%s。请从当前屏幕接管，接着往下走；"
                        "不要重复骨架已经成功的步骤。" % (
                            _brk1, _exp1,
                            " → ".join(str((x or {}).get("text") or (x or {}).get("do") or "")
                                       for x in _sk)[:160]))
        except Exception as e:
            print("[agent] 规划骨架执行异常（跳过）: %r" % (e,))

    # ================================ 关卡三 · 子目标状态机
    goals = []
    if SW_SUBGOAL and SL is not None:
        try:
            goals = SL.build_goals(plan)
        except Exception:
            goals = []
    if goals:
        print("[agent] 子目标 %d 个: %s" % (len(goals), " → ".join(g["goal"][:18] for g in goals)))
    goal_idx, goal_miss = 0, 0
    goal_retry = {}
    login_strikes, login_alerted = 0, False
    stall_resets = 0                       # "无进展重置"次数（≥3 → 兜底放弃）
    _HOME_DONE.clear()
    DEAD_SPOTS = set()
    _t_run0 = time.time()                  # 本次任务墙钟起点（用于总时长上限）
    # 迭代9：开工 HOME 预清理——上一任务的残留（全屏弹窗/浏览器页）会压住目标 App，
    # 先回桌面再由规划 open_app 拉起，避免开局就烧步数关弹窗（2026-10-19 浏览器更新框实证）。
    try:
        portal.key(3)                      # KEYCODE_HOME
        time.sleep(1.0)
    except Exception:
        pass
    if SCRIPT_BREAK_HINT[0]:
        history.append({"role": "user", "content": SCRIPT_BREAK_HINT[0]})
        SCRIPT_BREAK_HINT[0] = ""

    for step in range(1, max_steps + 1):
        t_step = time.time()
        # —— 总时长上限（2026-10-12：用户口径"不该烧到 60 步"）——
        #    到点就如实收尾，避免"无限空转"。默认 150 秒（可用 TIME_CAP 覆盖）。
        if TIME_CAP and (time.time() - _t_run0) > TIME_CAP:
            _m = "无法完成：已执行 %d 步、耗时 %.0f 秒仍未完成，按超时停止。" % (
                step - 1, time.time() - _t_run0)
            print("[agent] 总时长超限 → 停止：%s" % _m)
            tracer.log(step, "result", "超时停止")
            print("[agent] DONE: %s" % _m)
            tracer.log(step, "done", _m)
            tracer.close()
            return 0
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
            pre_elems = bridge_elements(dpy=DISPLAY) if DISPLAY > 0 else bridge_elements()
            if pre_elems:
                print("[step %d] portal 不可用，转用 root 桥树（%d 元素）" % (step, len(pre_elems)))
                tracer.log(step, "result", "portal离线→桥树 %d 元素" % len(pre_elems))
                state = {"phone_state": {"currentApp": "(桥)", "packageName": "",
                                         "keyboardVisible": False},
                         "a11y_tree": fake_tree_from_elems(pre_elems)}
            else:
                # 视觉兜底：微信等 App 会让 portal 直接报 "root filtered out"（读不到就抛错）
                ve = vision_elements(step, tracer)
                if ve:
                    print("[step %d] portal 读不到（App 屏蔽）→ 视觉兜底 %d 元素（推定前台=%s）"
                          % (step, len(ve), _LAST_PKG[0] or "?"))
                    pre_elems = ve
                    state = {"phone_state": {"currentApp": "(视觉)", "packageName": _LAST_PKG[0],
                                             "keyboardVisible": False},
                             "a11y_tree": fake_tree_from_elems(ve)}
                else:
                    print("[agent] portal 连续取状态失败且桥树/视觉都不可用，中止。")
                    aborted = True
                    break
        elems = collect_elements(state)
        cur_pkg = ""
        try:
            cur_pkg = (state.get("phone_state") or {}).get("packageName") or ""
        except Exception:
            pass
        if cur_pkg and not cur_pkg.startswith("("):
            _LAST_PKG[0] = cur_pkg
        # —— 迭代5：熄屏/锁屏识别 ——
        # 特征：前台包名是 systemui/Keyguard，且树里几乎没有目标 App 元素。
        # 熄屏时 a11y 手势全部无效（实测 open_app 会空指针、swipe 屏幕无变化），
        # 只有 WAKEUP 类按键可能有效 → 先自救一次，救不活立即 fail-fast（不烧预算）。
        _is_lock = (not cur_pkg.startswith("(")) and (
            "systemui" in cur_pkg.lower() or "keyguard" in cur_pkg.lower())
        if _is_lock:
            lock_strikes += 1
        else:
            lock_strikes = 0
        if lock_strikes >= 2:
            print("[agent] 检测到熄屏/锁屏（%s）→ 尝试唤醒自救" % cur_pkg)
            try:
                portal.key(224)   # KEYCODE_WAKEUP
                time.sleep(1.2)
                portal.key(82)    # MENU（无密码锁屏可顺带解锁）
                time.sleep(1.5)
            except Exception as e:
                print("[agent] 唤醒键通道异常: %r" % (e,))
            _st2 = None
            try:
                _st2 = portal.get_state()
            except Exception:
                pass
            _pkg2 = ""
            try:
                _pkg2 = ((_st2 or {}).get("phone_state") or {}).get("packageName") or ""
            except Exception:
                pass
            if "systemui" in _pkg2.lower() or "keyguard" in _pkg2.lower() or not _pkg2:
                tracer.log(step, "result", "熄屏/锁屏无法唤醒，中止")
                aborted = True
                result = ("无法执行：平板处于熄屏/锁屏状态且无法自动唤醒，"
                          "请点亮屏幕后重发任务。")
                print("[agent] %s" % result)
                break
            lock_strikes = 0
            state = _st2
            elems = collect_elements(state)
            cur_pkg = _pkg2
            _LAST_PKG[0] = cur_pkg
            print("[agent] 唤醒成功，前台=%s，继续执行" % cur_pkg)
        # —— 感知边界注入前：元素过少先等待重读（2026-10-22 新增）——
        #    实测（B站 T3）：点击 tab 后页面在加载骨架屏，a11y 树只剩 0-3 个元素，
        #    模型看到空清单就开始编「当前在助手控制台页面」→ 后面 10 多步全废。
        #    改为：元素 <5 时先等 1.2s 重读，最多 3 次；仍空才带着明确提示交给模型。
        try:
            _low = 0
            while len(elems) < 5 and _low < 3:
                _low += 1
                print("[step %d] 元素过少（%d）→ 等待 %.1fs 重读（%d/3）"
                      % (step, len(elems), 1.2 * _low, _low))
                time.sleep(1.2 * _low)
                _st_r = None
                try:
                    _st_r = portal.get_state()
                except Exception:
                    pass
                if _st_r:
                    state = _st_r
                    elems = collect_elements(_st_r)
                    try:
                        cur_pkg = ((_st_r.get("phone_state") or {}).get("packageName")
                                   or cur_pkg)
                    except Exception:
                        pass
            if len(elems) < 5:
                print("[step %d] 重读后仍只有 %d 个元素（可能仍在加载）" % (step, len(elems)))
        except Exception as _e_low:
            print("[step %d] 低元素重读异常（跳过）: %r" % (step, _e_low))
        # —— 已知锚点注入（2026-10-22）：a11y 读不到的自绘入口（如 B站HD 搜索栏）
        #    以虚拟元素形式并入清单，模型可直接 pick，不用猜坐标。
        try:
            if cur_pkg and not str(cur_pkg).startswith("("):
                _before = len(elems)
                elems = inject_anchor_elems(elems, cur_pkg)
                if len(elems) > _before:
                    print("[step %d] 注入 App 锚点 %d 个（%s）"
                          % (step, len(elems) - _before, cur_pkg))
        except Exception as _e_anc:
            print("[step %d] 锚点注入异常（跳过）: %r" % (step, _e_anc))
        # —— 目标 App 失联自愈（2026-10-22 新增）——
        #    实测（B站 T1）：open_app 之后前台仍不是目标 App（启动广告/登录墙/被系统切走），
        #    模型会连续好几步问"我是不是在控制台界面"，白白烧步数。
        #    规则：连续 2 步的目标 App 不在前台 → 确定性 force-stop + 拉起 + 等 3 秒。
        try:
            _tgt_pkg = (plan or {}).get("app_package") or ""
            if _tgt_pkg and cur_pkg and not str(cur_pkg).startswith("(") and cur_pkg != _tgt_pkg:
                fg_miss[0] += 1
            else:
                fg_miss[0] = 0
            if fg_miss[0] >= 2:
                fg_miss[0] = 0
                print("[agent] 目标 App(%s) 连续不在前台（当前 %s）→ 确定性拉起"
                      % (_tgt_pkg, cur_pkg))
                tracer.log(step, "result", "目标失联→拉起 %s" % _tgt_pkg)
                try:
                    subprocess.run(["/system/bin/sh", "-c", "am force-stop %s" % _tgt_pkg],
                                   capture_output=True, timeout=15)
                except Exception:
                    pass
                time.sleep(1.0)
                try:
                    portal.open_app(_tgt_pkg)
                except Exception:
                    try:
                        subprocess.run(["/system/bin/sh", "-c",
                                        "monkey -p %s -c android.intent.category.LAUNCHER 1"
                                        % _tgt_pkg], capture_output=True, timeout=20)
                    except Exception:
                        pass
                time.sleep(3.5)
                _st4 = None
                try:
                    _st4 = portal.get_state()
                except Exception:
                    pass
                if _st4:
                    state = _st4
                    elems = collect_elements(_st4)
                    try:
                        cur_pkg = ((_st4.get("phone_state") or {}).get("packageName")
                                   or cur_pkg)
                    except Exception:
                        pass
                    print("[agent] 拉起后前台=%s，元素 %d" % (cur_pkg, len(elems)))
        except Exception as _e_fg:
            print("[step %d] 目标失联自愈异常（跳过）: %r" % (step, _e_fg))
        # —— 权限弹窗处理（2026-10-22 新增，确定性规则、不花 token）——
        #    酷安实测会连续弹「获取设备信息」「拨打电话」，模型会去点「允许」（误授权+带偏任务）。
        #    这里在交给模型决策之前就直接点「拒绝」。
        try:
            for _pn in range(2):
                if not _deny_permission_dialog(portal, elems, tracer):
                    break
                _st_p = None
                try:
                    _st_p = portal.get_state()
                except Exception:
                    pass
                if _st_p:
                    elems = collect_elements(_st_p)
                    state = _st_p
                else:
                    break
            else:
                pass
        except Exception as _e_p:
            print("[step %d] 权限弹窗处理异常（跳过）: %r" % (step, _e_p))
        # —— 登录提示处理（**不早停**）：先关掉继续用；反复出现才叫人来登录 ——
        #   2026-10-12 用户口径：很多 App 只是"弹一下"登录，关掉就能继续；一看到就停是错的。
        if SL is not None and DISPLAY == 0:
            try:
                _tp = (plan or {}).get("app_package") or ""
                if SL.login_wall(elems) and (not _tp or cur_pkg == _tp):
                    login_strikes += 1
                    _closed = _dismiss_login(portal, elems, tracer)
                    print("[step %d] 检测到登录提示（第 %d 次，%s）"
                          % (step, login_strikes, "已尝试关闭并继续" if _closed else "未找到关闭按钮"))
                    tracer.log(step, "result", "登录提示 第%d次(%s)"
                               % (login_strikes, "已关闭" if _closed else "无关闭按钮"))
                    # 迭代6：关闭动作后**复查**——若已摆脱登录墙，说明这是引导页/弹层而非真登录墙，
                    # 不累计报警（2026-10-19 同花顺"登录流程指南"页误报实证）。
                    if _closed:
                        _still = True
                        try:
                            _st3 = portal.get_state()
                            _still = SL.login_wall(collect_elements(_st3))
                        except Exception:
                            _still = True
                        if not _still:
                            print("[agent] 关闭后已摆脱登录墙（实为引导页/弹层）→ 继续任务，不计入报警")
                            login_strikes = 0
                            time.sleep(0.8)
                            continue
                    if login_strikes >= 2 and not login_alerted:
                        login_alerted = True
                        alert_user("小工头：需要你登录",
                                   "%s 反复要求登录，请打开手机登录后再说一次任务。"
                                   % (cur_pkg or "目标应用"), tracer)
                    if login_strikes >= 3:
                        _m = "无法完成：%s 反复要求登录，已提醒你处理" % (cur_pkg or "目标应用")
                        print("[agent] 登录提示反复出现 → 停并已提醒：%s" % _m)
                        print("[agent] DONE: %s" % _m)
                        tracer.log(step, "done", _m)
                        tracer.close()
                        return 0
                    if _closed:
                        time.sleep(1.0)
                        continue                    # 关掉后重新感知、继续任务
                else:
                    login_strikes = 0
            except Exception as e:
                print("[step %d] 登录提示处理异常（跳过）: %r" % (step, e))
        if DISPLAY > 0:
            # 正式模式：感知只认影子屏（portal 会跟着"最后被触屏的那块屏"漂移；
            # 桥树天然含全部显示屏 → 按 displayId 过滤）。
            # 注意：影子屏空树时**不要**回退用 portal 树——那是主屏的元素，点下去会指错地方。
            be = bridge_elements(dpy=DISPLAY)
            if len(be) < 3:
                print("[step %d] 影子屏桥树仅 %d 个元素（按空屏处理，不回退主屏）" % (step, len(be)))
                tracer.log(step, "result", "影子屏桥树元素不足: %d" % len(be))
            elems = be
            try:
                fp = display_focus_pkg(DISPLAY)
                if fp:
                    cur_pkg = fp
            except Exception:
                pass
        elif pre_elems is not None:
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
        # —— 视觉兜底：a11y 树被 App 屏蔽（微信 8.0.52+：根被过滤，树里只剩状态栏）
        #    → 截图 + 多模态模型 → 伪元素清单（下游零改动）；上游已用视觉的步不再重复调用 ——
        if DISPLAY == 0 and pre_elems is None and cur_pkg in vision_apps():
            ve = vision_elements(step, tracer)
            if ve:
                elems = ve
            elif elems:
                print("[step %d] 视觉兜底失败，回退元素树（%d 元素，可能只剩状态栏）"
                      % (step, len(elems)))
        # —— 关卡一 · 起点归位：目标 App 在前台但不在已知页（或落在死胡同页）→ 先返航 ——
        try:
            if cur_pkg and not cur_pkg.startswith("("):
                if _maybe_home_reset(cur_pkg, elems, portal, tracer, _HOME_DONE, fg_pkg=cur_pkg):
                    _el3, _c3 = _script_elems(portal)
                    if _el3:
                        elems = _el3
        except Exception as e:
            print("[step %d] 起点归位异常（跳过）: %r" % (step, e))
        # —— 页面身份（三级锚点）：坐标注入按页面过滤 ——
        cur_page = ""
        try:
            cur_page = page_of(cur_pkg, elems)
            if cur_page:
                tracer.log(step, "result", "页面身份: %s" % cur_page)
        except Exception:
            cur_page = ""
        # —— 经验坐标注入：App 卡片实测坐标（如微博「更多热搜」「热搜」标签）→ 虚拟元素（Jev/qwen 可直接点） ——
        #    2026-10-11：页面过滤 + 坐标自校验 + 本次失效名单
        virt_injected = []
        try:
            for _sp in app_coords(cur_pkg, elems, cur_page, DEAD_SPOTS):
                virt_injected.append(_sp)
                elems.append((len(elems), _sp["x"], _sp["y"],
                              "%s【经验坐标】" % _sp["label"], True))
                print("[step %d] 经验坐标注入: %s (%d,%d)"
                      % (step, _sp["label"], _sp["x"], _sp["y"]))
                tracer.log(step, "result", "经验坐标注入: %s (%d,%d)"
                           % (_sp["label"], _sp["x"], _sp["y"]))
        except Exception:
            pass
        # —— 坐标封禁：同一坐标**累计**点击 ≥4 次（不管屏幕变不变）→ 从元素清单里剔除 ——
        #    2026-10-12 实证：今日头条/抖音里模型反复点同一个无效坐标，靠"屏幕无变化"判不出来
        #    （信息流一直在刷新，屏幕 hash 一直在变），最终烧光步数。
        try:
            _bad = [k for k, n in tap_seen.items() if n >= 4]
            if _bad:
                _b4 = len(elems)
                elems = [e for e in elems
                         if not any(abs(e[1] - kx * 8) < 60 and abs(e[2] - ky * 8) < 60
                                    for (kx, ky) in _bad)]
                if len(elems) != _b4:
                    print("[step %d] 坐标封禁：剔除 %d 个元素（这些坐标已多次无效）"
                          % (step, _b4 - len(elems)))
                    tracer.log(step, "result", "坐标封禁剔除 %d 个元素" % (_b4 - len(elems)))
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
                    # 经验坐标失效标记：来自卡片的虚拟元素点了没反应 → 本次运行内不再注入
                    try:
                        if SL is not None and last_pick and "【经验坐标】" in last_pick and cur_pkg:
                            _k = SL.spot_key(cur_pkg, last_pick.replace("【经验坐标】", ""))
                            if _k not in DEAD_SPOTS:
                                DEAD_SPOTS.add(_k)
                                print("[step %d] 经验坐标失效标记: %s" % (step, _k))
                                tracer.log(step, "result", "经验坐标失效: %s" % _k)
                    except Exception:
                        pass
                history.append({"role": "user", "content": note})
            elif changed:
                no_effect.clear()   # 屏幕已变化（加载完成/页面切换）→ 解除全部"无效"标记
            last_sig = None
        # —— 榜单收集推进："第N条/前N名"任务：数据不足时催促滚动，足够时直接给出名次 ——
        _rn = parse_rank_n(task) or parse_rank_n((plan or {}).get("intent") or "")
        _rn_global[0] = _rn or 0
        if _rn and step >= 2:
            if len(rank_acc) >= _rn + 2:
                if not rank_ready:
                    _nth = rank_nth(rank_acc, _rn)
                    _is_topn = bool(re.search(r"前\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[条名位]",
                                              (task or "") + " " + ((plan or {}).get("intent") or "")))
                    if _is_topn:
                        # "前N条"任务：收集够了就必须收工，禁止继续滚动（实测会震荡 44 步）
                        history.append({"role": "user", "content":
                                        "（系统强制）榜单数据已收集足够（%d 条）。**立即停止滚动**，"
                                        "把前 %d 条标题按序号列出来并输出 done。"
                                        "缺少的个别条目就用已看到的，不要为了完整性反复来回滚动。"
                                        % (len(rank_acc), _rn)})
                        print("[step %d] 榜单收集完成（前%d条）→ 已要求立即作答，此后禁止滚动"
                              % (step, _rn))
                        rank_ready = True
                    elif _nth:
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
        # —— 关卡三 · 子目标：先验收已完成的目标，再注入「当前子目标」（2026-10-11） ——
        goal_text = ""
        if goals and SL is not None:
            try:
                while goal_idx < len(goals):
                    _gr = SL.goal_reached(goals, goal_idx, elems, "", None)
                    if _gr is None:          # 该目标没锚点 → 无法验收，视为进行中
                        break
                    if not _gr:
                        break
                    print("[step %d] 子目标达成：%s" % (step, goals[goal_idx]["goal"][:24]))
                    tracer.log(step, "result", "子目标达成: %s" % goals[goal_idx]["goal"][:24])
                    _nxt = ("接下来做：「%s」" % goals[goal_idx + 1]["goal"]) \
                        if goal_idx + 1 < len(goals) else "全部子目标已完成，请 done 收尾并给出答案。"
                    history.append({"role": "user", "content":
                                    "（系统）✅ 已完成子目标「%s」。%s"
                                    % (goals[goal_idx]["goal"], _nxt)})
                    goal_idx += 1
                    goal_miss = 0
                    prog.score = 0
                if goal_idx < len(goals):
                    goal_text = render_goals(goals, goal_idx)
                    goal_miss += 1
                    if goal_miss >= 3 and goal_idx not in goal_hinted:
                        # ⚠️ 只做**软提示**，绝不判失败、不干净停（2026-10-12 实证）：
                        #    子目标的 verify 是规划器猜的特征词，经常不准；硬判"未达成 → 回退
                        #    → 重试 3 次 → 干净停"会把**本来能完成**的任务当场判死。
                        #    且**同一目标只提示一次**（每 3 步刷一次会持续干扰模型）。
                        #    真正的"卡住"由 Progress 无进展分 / 硬阻断 / 坐标封禁负责。
                        goal_miss = 0
                        goal_hinted.add(goal_idx)
                        _fb = goals[goal_idx].get("fallback") or ""
                        print("[step %d] 子目标未达成 → 软提示（仅一次，不判失败）：%s"
                              % (step, goals[goal_idx]["goal"][:20]))
                        history.append({"role": "user", "content":
                                        "（系统提示）你可能还没到「%s」。若你其实已在该页面，"
                                        "**请忽略本提示**，继续按当前屏幕推进；"
                                        "若确实没到，可尝试：%s"
                                        % (goals[goal_idx]["goal"], _fb or "换个入口 / 点对应导航")})
            except Exception as e:
                print("[step %d] 子目标处理异常（跳过）: %r" % (step, e))
                goal_text = ""
        try:
            # 2026-10-22：模型调用**前**打点，才能量出真实推理耗时
            # （此前 prompt/reply 都在返回后一起写，两个 ts 完全相同 → 度量全是 0）
            tracer.log(step, "prompt_start", "", engine=engine_now)
            act, eng, dec_dt, ti = decide(step, task, state, history, engine_now, elems,
                                          experience, related_apps, plan, goal_text)
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
            # 2026-10-22 修高危 bug：原逻辑只匹配"第N个/条/名/位"，于是
            # **"打开第一个视频"** 也被当成榜单任务，系统把模型已答对的内容
            # （《萌猫大集合》/喵星cat人/62.2万）覆盖成了无关的"悲伤汇成海洋"。
            # 修正：必须任务本身带**排行榜语义**才允许系统覆盖。
            RANK_TASK_WORDS = ("排行", "榜单", "热搜", "排名", "榜上", "热榜", "第几",
                               "前几", "前三", "前3", "前五", "前5", "前十", "前10")
            sys_locked = False
            try:
                _rank_task = any(w in (task or "") for w in RANK_TASK_WORDS) or \
                    any(w in ((plan or {}).get("intent") or "") for w in RANK_TASK_WORDS)
                m_nth = re.search(r"第\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[条名位个]", task or "")
                if m_nth and _rank_task:
                    _n2 = _cn2int(m_nth.group(1))
                    _sys = rank_nth(rank_acc, _n2)
                    if _sys:
                        summary = "第 %d 条是：%s" % (_n2, _sys)
                        sys_locked = True
                        print("[agent] 榜单第%d条（系统确定）: %s" % (_n2, _sys[:50]))
                elif m_nth and not _rank_task:
                    print("[agent] 跳过榜单覆盖：任务无排行榜语义（'第N个'只是序数，不是排名）")
            except Exception:
                pass
            # —— "前N条"任务：数据够 → 系统直接组答案（2026-10-22，0 模型成本）——
            #    实测：模型受屏幕视野限制，只能复述当前屏看到的几条，
            #    而系统已跨步累积了 31 条（含第 7~10 条）。让模型回忆 = 必然漏条，
            #    让它凑数 = 拿导航标签填坑。两条都错 → 干脆用累积数据确定性作答。
            try:
                _topn = re.search(r"前\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[条名位]",
                                  (task or "") + " " + ((plan or {}).get("intent") or ""))
                if _topn and rank_acc and not str(summary or "").startswith("无法"):
                    _n3 = _cn2int(_topn.group(1))
                    _NAV = ("微博搜索", "热搜榜", "话题榜", "文娱榜", "要闻榜", "新时代",
                            "同城榜", "好友搜", "实时热点", "搜索", "登录", "更多")
                    # rank_acc 的结构是 {title: score} → items() 给出 (title, score)
                    _pairs = sorted(rank_acc.items(), key=lambda kv: -(kv[1] or 0))
                    _items = [(sc, ti) for ti, sc in _pairs
                              if ti and len(str(ti).strip()) >= 4
                              and not any(str(ti).strip() == w or str(ti).strip().startswith(w)
                                          for w in _NAV)
                              and not re.fullmatch(r"[\d\s,.]+", str(ti).strip())]
                    if _n3 and len(_items) >= _n3:
                        summary = "前%d条：%s" % (
                            _n3, "; ".join("%d. %s" % (i + 1, ti)
                                           for i, (_sc, ti) in enumerate(_items[:_n3])))
                        sys_locked = True
                        print("[agent] 用系统累积榜单作答（可选 %d 条，取前 %d）：0 模型成本"
                              % (len(_items), _n3))
                        tracer.log(0, "result", "系统累积作答 前%d条（候选%d）" % (_n3, len(_items)))
            except Exception as _e_topn:
                print("[agent] 前N条系统作答异常（跳过）: %r" % (_e_topn,))
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
            # —— 系统真值交叉核对（0 模型）：WiFi/电量这类能用系统 API 直读的，优先信系统 ——
            if summary and not summary.startswith("无法") and not sys_locked:
                try:
                    _tr = _sys_truth(task)
                    _bad = ""
                    if _tr.get("wifi") and _tr["wifi"] not in summary:
                        _bad = "系统实测当前 WiFi 是「%s」，你的答案里没有它" % _tr["wifi"]
                    elif _tr.get("battery") and _tr["battery"] not in summary:
                        _bad = "系统实测电量是 %s%%，你的答案里没有它" % _tr["battery"]
                    if _bad:
                        done_rejects += 1
                        print("[step %d] DONE 被系统真值驳回：%s" % (step, _bad))
                        tracer.log(step, "result", "done被系统真值驳回: %s" % _bad)
                        history.append({"role": "assistant",
                                        "content": json.dumps(act, ensure_ascii=False)})
                        history.append({"role": "user", "content":
                                        "系统交叉核对发现你的答案与手机实际状态不符：%s。"
                                        "请以系统实测为准重新作答。" % _bad})
                        time.sleep(1.0)
                        continue
                except Exception as e:
                    print("[step %d] 系统真值核对异常（跳过）: %r" % (step, e))
            # —— 本地规则复核（0 模型，先行）：规则能确定的直接驳回，省一次模型调用 ——
            if summary and not summary.startswith("无法") and not sys_locked and SW_REVIEW \
                    and SL is not None:
                try:
                    _r_ok, _r_why = SL.review_answer(task, summary, plan, family)
                except Exception:
                    _r_ok, _r_why = True, ""
                if not _r_ok:
                    done_rejects += 1
                    print("[step %d] DONE 被本地规则驳回：%s" % (step, _r_why))
                    tracer.log(step, "result", "done被本地规则驳回: %s" % _r_why)
                    history.append({"role": "assistant",
                                    "content": json.dumps(act, ensure_ascii=False)})
                    history.append({"role": "user", "content":
                                    "你的答案被系统**本地规则**驳回：%s。"
                                    "请重新核对屏幕上的真实内容再作答；若确实无法完成，"
                                    "请输出 done 并如实说明「无法完成：原因」。" % _r_why})
                    time.sleep(1.0)
                    continue
            # —— 防幻觉复核：结果须能在屏幕上找到依据（"无法完成"如实报告的直接放行） ——
            screen_text = " ".join(e[3] for e in elems)
            # —— 导航标签黑名单（2026-10-22 实测驱动，确定性、0 模型成本）——
            #    微博热搜实测：模型把页面 tab（微博搜索/热搜榜/话题榜）当成第 8/9/10 条热搜，
            #    校验器驳回 2 次后第 3 次用同一个错答案还是过了 → 必须确定性拦住。
            NAV_LABELS = ("微博搜索", "热搜榜", "话题榜", "文娱榜", "要闻榜", "新时代",
                          "同城榜", "好友搜", "实时热点", "我的", "发现", "首页", "消息")
            try:
                _hits = [w for w in NAV_LABELS if w in (summary or "")]
                if len(_hits) >= 2 and not (summary or "").startswith("无法"):
                    done_rejects += 1
                    v_reason = ("答案里出现 %d 个页面导航标签（%s），这些不是数据条目"
                                % (len(_hits), "、".join(_hits[:4])))
                    print("[step %d] DONE 被驳回（导航标签）：%s" % (step, v_reason))
                    tracer.log(step, "result", "done被驳回(导航标签): %s" % v_reason)
                    history.append({"role": "user", "content":
                                    "（系统）你的答案把页面上的导航/标签文字（%s）当成了数据条目。"
                                    "请只用真正的内容条目作答；缺的条目宁可少报，不要用导航词凑数。"
                                    % "、".join(_hits[:4])})
                    if done_rejects >= 3:
                        print("[agent] 导航标签反复出现 → 停止（不再浪费步数）")
                        print("[agent] DONE: 无法完成：只读到导航标签，未能可靠提取数据条目")
                        tracer.log(step, "done", "导航标签反复出现，停止")
                        tracer.close()
                        return 0
                    continue
            except Exception:
                pass
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
                    # —— 关卡二 · 成功即固化（候选脚本；跑通两次才转正）——
                    if SW_SCRIPT and SL is not None and DISPLAY == 0:
                        try:
                            _cand = SL.save_candidate(
                                task, plan, exec_log, family, cur_pkg,
                                done_rejects=done_rejects,
                                max_block_streak=max_block_streak)
                            if _cand:
                                print("[agent] 脚本候选已固化: %s（%d 步）→ %s"
                                      % (_cand.get("name"), len(_cand.get("steps") or []),
                                         "~/bridge/skills/scripts/%s.json" % _cand.get("id")))
                                tracer.log(step, "result", "脚本候选固化: %s" % _cand.get("id"))
                        except Exception as e:
                            print("[agent] 脚本固化失败（忽略）: %r" % (e,))
            return 0

        # —— pick 解析（**准确率关键**）：模型只说"第几号元素"，坐标由本地精确给出 ——
        #    2026-10-12：让模型抄坐标 / 猜元素名是最大的错误来源；改成"报编号"后，
        #    点错、名字对不上这两类失败从根上消失。
        if a == "tap":
            _rp = resolve_pick(elems, act.get("pick"))
            if _rp:
                act["x"], act["y"] = _rp[0], _rp[1]
                act["_pick_label"] = _rp[2]
                # —— pick 索引纠偏（2026-10-22 新增，v2 修正）——
                #    实测（B站 T3）：模型 pick=2 想点「热门」，实际索引 2 是「推荐」（偏一位）。
                #    v1 用"整串标签是否出现在 thought"判定，踩坑：a11y 的复合标签是
                #    `热门,5之3,标签`，thought 里只写「热门」→ 被判"不匹配"→ 反而改点成「首页」。
                #    v2 改为**词元匹配**：把标签按分隔符拆段，任一段（≥2字）出现在 thought 即算命中。
                try:
                    import re as _re_pc

                    def _hit(lab, th):
                        parts = _re_pc.split(r"[,，|/、\s]+", str(lab or ""))
                        return any(len(p) >= 2 and p in th for p in parts)

                    _th = str(act.get("thought") or "")
                    _picked = str(_rp[2] or "")
                    if _th and _picked and not _hit(_picked, _th):
                        _cands = [e for e in elems
                                  if e[3] and str(e[3]) != _picked and _hit(str(e[3]), _th)]
                        if len(_cands) == 1:
                            _best = _cands[0]
                            act["x"], act["y"] = _best[1], _best[2]
                            act["_pick_label"] = str(_best[3])
                            print("[step %d] pick 索引纠偏: %r → %r（以 thought 里的标签为准）"
                                  % (step, _picked, _best[3]))
                            tracer.log(step, "result", "索引纠偏 %r→%r" % (_picked, _best[3]))
                        elif len(_cands) > 1:
                            print("[step %d] 索引纠偏跳过：thought 命中 %d 个候选，无法确定"
                                  % (step, len(_cands)))
                except Exception as _e_pc:
                    print("[step %d] 索引纠偏跳过: %r" % (step, _e_pc))
            else:
                _rp2 = label_at(elems, act.get("x", -1), act.get("y", -1))
                if _rp2:
                    act["_pick_label"] = _rp2

        # —— 盲点拦截（2026-10-22 新增）——
        #    实测（酷安 T1）：模型会凭"记忆里的布局"报一个坐标，而该坐标附近
        #    在当前元素清单里根本没有元素 → 点是空白 → 什么也不发生 → 再点一次。
        #    这里当场记下并告警，不等 3 步"无进展"才发现。
        if a == "tap" and not act.get("_pick_label"):
            _bx, _by = act.get("x", -1), act.get("y", -1)
            _near = label_at(elems, _bx, _by, tol=70)
            if not _near:
                blind_taps[0] += 1
                _cov = percept_coverage(elems)
                _hint = ("（系统警告）你刚点的坐标 (%d,%d) 附近**没有任何元素**，"
                         "点下去不会触发任何东西。请从上面的元素清单里用 pick 报编号来点击；"
                         "如果目标元素不在清单里，说明它不在当前可见范围内，先返回/滚动。" % (_bx, _by))
                history.append({"role": "user", "content": _hint})
                print("[step %d] 盲点点击 (%d,%d) 无邻近元素 → 已告警（累计 %d 次）"
                      % (step, _bx, _by, blind_taps[0]))
                tracer.log(step, "result", "盲点点击 (%d,%d)" % (_bx, _by))

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
        # —— 滚动震荡拦截（2026-10-22 实测驱动）——
        #    微博热搜实测：数据在第 7 步就收集够了，模型却在"下滚看7-10条 / 上滚看1-4条"
        #    之间来回震荡 44 步，把 51 步预算全烧光。
        #    两道闸门：
        #      ① 榜单数据已够（rank_ready）→ 禁止任何滚动/滑动，必须作答
        #      ② 方向来回切换 ≥4 次 → 判定震荡，禁止再滚动
        _is_scroll = a in ("scroll", "swipe")
        if _is_scroll:
            _dir = (act.get("direction") or "").lower() if a == "scroll" else ""
            if _dir and scroll_last_dir[0] and _dir != scroll_last_dir[0]:
                scroll_osc[0] += 1
            scroll_last_dir[0] = _dir or scroll_last_dir[0]
        elif a not in ("wait",):
            scroll_osc[0] = 0
        osc_blocked = False
        if _is_scroll and rank_ready and _rn_global[0]:
            # 只禁止"往下滚"（越滚越远）；允许一次向上滚回顶部，否则拿不到第 1~5 条
            _dir2 = (act.get("direction") or "").lower() if a == "scroll" else \
                ("up" if (act.get("y2", 0) or 0) < (act.get("y1", 0) or 0) else "down")
            if _dir2 == "up" and back_up[0] < 2:
                back_up[0] += 1
                print("[step %d] 允许向上滚回顶部（%d/2）" % (step, back_up[0]))
            else:
                osc_blocked = True
                _osc_msg = ("榜单数据已收集足够（%d 条），**禁止再往下滚**。"
                            "请立刻输出 {\"action\":\"done\",\"summary\":\"前%d条：...\"}，"
                            "把已看到的标题按序号列出来；缺的宁可少报，不要用导航词凑数。"
                            % (len(rank_acc), _rn_global[0]))
        elif _is_scroll and scroll_osc[0] >= 4:
            osc_blocked = True
            _osc_msg = ("你在来回滚动（已 %d 次方向切换）但屏幕内容没有推进。"
                        "停止滚动，用当前已经拿到的信息作答；如果确实还缺，改成点击具体条目进入。"
                        % scroll_osc[0])
        # —— 贯穿件 B · 硬闸门（执行前；来自 guards.json，高频错误模式编译而成）——
        guard_blocked, guard_msg = False, ""
        if SW_GUARDS and SL is not None:
            try:
                _lbl = ""
                if a == "tap":
                    _lbl = str(act.get("_pick_label")
                               or label_at(elems, act.get("x", -1), act.get("y", -1)) or "")
                guard_blocked, guard_msg = SL.guard_check(
                    act, {"pkg": cur_pkg, "page": cur_page, "label": _lbl})
            except Exception:
                guard_blocked = False
        # 坐标封禁（硬拦截）：同一坐标本次运行内累计点 ≥4 次仍无进展 → 直接拒绝
        #   2026-10-12 实证：模型会从对话历史里**照抄自己之前的动作**，即使该坐标已从
        #   元素清单里被剔除也会再点 → 光"过滤元素"不够，必须在执行层直接拦下。
        coord_banned = (sig is not None and sig[0] == "tap" and tap_seen.get(sig, 0) >= 4)
        blocked = (sig is not None and (fail_counts.get(sig, 0) >= _fail_lim
                                        or no_effect.get(sig, 0) >= 2)) \
            or sw_blocked or guard_blocked or coord_banned or osc_blocked
        if blocked:
            ok = False
            if coord_banned:
                exec_err = ("该坐标 (%d,%d) 本次已点 %d 次仍无进展，已封禁；"
                            "请改点别的元素 / 换一种做法（换入口、滚动、换页签）"
                            % (sig[1] * 8, sig[2] * 8, tap_seen[sig]))
                print("[step %d] 坐标封禁拦截: %s" % (step, exec_err[:70]))
                tracer.log(step, "result", "坐标封禁拦截: %s" % exec_err[:90])
            elif guard_blocked:
                exec_err = guard_msg or "硬闸门拦截"
                print("[step %d] GUARD 拦截: %s" % (step, exec_err[:70]))
                tracer.log(step, "result", "硬闸门拦截: %s" % exec_err[:90])
            elif sw_blocked:
                exec_err = "相同滑动已连续 %d 次未到达目标" % sw_repeat
                print("[step %d] BLOCK 滑动迷路: %s" % (step, sw_sig))
            elif osc_blocked:
                exec_err = _osc_msg
                print("[step %d] BLOCK 滚动震荡: %s" % (step, _osc_msg[:80]))
                tracer.log(step, "result", "滚动震荡拦截: %s" % _osc_msg[:90])
                history.append({"role": "user", "content": "（系统强制）" + _osc_msg})
            else:
                exec_err = "该动作已连续多次失败/无效果（很可能无效/目标不存在）"
                print("[step %d] BLOCK 重复失败动作: %s" % (step, sig))
        else:
            try:
                if a == "tap":
                    tgt = act.get("_pick_label") or label_at(elems, act.get("x", -1),
                                                             act.get("y", -1))
                    if tgt and any(w in tgt for w in DANGER_WORDS):
                        ok = False
                        exec_err = ("安全护栏：不执行「%s」类操作（agent 不处理登录/验证码凭证）" % tgt)
                        print("[step %d] 护栏拦截: %s" % (step, tgt))
                        tracer.log(step, "result", "护栏拦截: %s" % tgt)
                    elif act.get("pick") and "_pick_label" not in act:
                        ok = False
                        exec_err = ("pick「%s」在元素清单里找不到（编号越界或文本不存在）；"
                                    "请改用清单里真实存在的编号" % act.get("pick"))
                        print("[step %d] pick 无效: %s" % (step, exec_err[:70]))
                    elif "x" not in act or "y" not in act:
                        ok = False
                        exec_err = "tap 既没有有效 pick，也没有坐标"
                    elif DISPLAY > 0:
                        input_cmd(["-d", DISPLAY, "tap", act["x"], act["y"]])
                    else:
                        portal.tap(act["x"], act["y"])
                elif a == "swipe":
                    if DISPLAY > 0:
                        input_cmd(["-d", DISPLAY, "swipe", act.get("x1", 0), act.get("y1", 0),
                                   act.get("x2", 0), act.get("y2", 0), act.get("duration", 500)])
                    else:
                        portal.swipe(act.get("x1", 0), act.get("y1", 0), act.get("x2", 0),
                                     act.get("y2", 0), act.get("duration", 500))
                elif a == "scroll":
                    _up = (act.get("direction") or "down").lower() == "up"
                    try:
                        detect_screen_size(portal)
                        _zone = 0
                        if last_hash is not None and last_hash == prev_hash and scroll_streak >= 1:
                            _zone = scroll_zone[0] = (scroll_zone[0] + 1) % 3
                            print("[step %d] 滚动无效自动换位 → zone %d" % (step, _zone))
                        _p = scroll_points(act.get("direction") or "down", _zone)
                    except Exception:
                        _p = (540, 700, 540, 1700, 500) if _up else (540, 1700, 540, 700, 500)
                    if DISPLAY > 0:
                        input_cmd(["-d", DISPLAY, "swipe"] + list(_p))
                    else:
                        portal.swipe(*_p)
                elif a == "input_text":
                    if DISPLAY > 0:
                        try:
                            portal.input_text(act.get("text", ""), act.get("clear", False))
                        except Exception:
                            input_cmd(["-d", DISPLAY, "text", str(act.get("text", ""))])
                    else:
                        portal.input_text(act.get("text", ""), act.get("clear", False))
                elif a == "key":
                    if DISPLAY > 0:
                        input_cmd(["-d", DISPLAY, "keyevent", act.get("key_code", 4)])
                    else:
                        portal.key(act.get("key_code", 4))
                elif a == "open_app":
                    want = act.get("package", "")
                    real = resolve_package(want, apps)
                    # —— open_app 幂等（2026-10-22 实测驱动）——
                    #    微博任务实测：Chrome 已在前台（显示的是控制台页面），模型反复
                    #    open_app chrome → 启动无变化 → 被判"重复失败动作"拦 3 次 → 7 步放弃。
                    #    改为：已在目标 App 前台时不重复启动，直接告知"你已经在里面了，做下一步"。
                    if real and cur_pkg == real:
                        ok = True
                        _idem = ("（系统提示）你已经就在 %s 里了，重复打开不会改变任何东西。"
                                 "请直接执行下一步（例如点地址栏输入网址、点搜索框输入关键词）。"
                                 % (act.get("package") or real))
                        history.append({"role": "user", "content": _idem})
                        print("[step %d] open_app 幂等跳过：%s 已在前台 → 提示改做下一步"
                              % (step, real))
                        tracer.log(step, "result", "open_app 幂等跳过(%s)" % real)
                        act["action"] = "wait"
                        a = "wait"
                        act["seconds"] = 0.3
                        no_effect.pop(sig, None)   # 幂等跳过不算"点了没效果"
                        real = None
                    if real is None:
                        pass
                    elif apps and resolve_package(want, apps) is None:
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
                        if DISPLAY > 0:
                            _err = shadow_open_app(real or want, DISPLAY)
                            if _err:
                                ok = False
                                exec_err = "影子屏启动失败：%s" % _err
                            else:
                                time.sleep(3.0)
                        else:
                            portal.open_app(real or want)
                            _LAST_PKG[0] = real or want
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
        prev_hash = last_hash               # 2026-10-19 迭代3：留两步前指纹判"连滚无变化"
        last_sig, last_ok, last_hash = sig, ok, screen_hash
        last_pick = str(act.get("pick") or "")
        # tap 坐标累计计数（≥4 次封禁；不依赖屏幕是否变化）
        if sig is not None and sig[0] == "tap":
            tap_seen[sig] = tap_seen.get(sig, 0) + 1
            # qwen 的 tap 没有 pick 字段 → 用"本步注入的虚拟坐标"反查，供失效标记使用
            if not last_pick:
                for _v in virt_injected:
                    if abs(_v["x"] - sig[1] * 8) < 40 and abs(_v["y"] - sig[2] * 8) < 40:
                        last_pick = _v["label"] + "【经验坐标】"
                        break
        # 统计（供失败归类 / 脚本固化）
        if elems:
            min_elems_seen = min(min_elems_seen, len(elems))
        if not ok and exec_err:
            errs.append(exec_err)
        try:
            if cur_pkg and (app_cards().get(cur_pkg) or {}).get("pages") and not cur_page:
                anchor_miss += 1
        except Exception:
            pass
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
            if block_streak > max_block_streak:
                max_block_streak = block_streak
            extra = ""
            if related_apps and a == "open_app":
                extra = " 本机可用的相关应用：" + "、".join(
                    "%s(%s)" % (ra["label"], ra["package"]) for ra in related_apps) + "。"
            if coord_banned:
                msg = ("上一步没有执行（坐标已封禁）：%s。**不要再点这个位置**，"
                       "请从屏幕元素清单里换一个元素，或改用滚动/切换页签/换入口。"
                       % (exec_err or ""))
            elif guard_blocked:
                msg = ("上一步没有执行（硬闸门拦截）：%s 请换一种做法。" % (exec_err or ""))
            elif sw_blocked:
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
            # **兜底放弃**（2026-10-12 用户口径：不该烧到 60 步才停）：重置 3 次仍无进展
            # → 判定"这条路走不通"，如实收尾，不再空转。
            stall_resets += 1
            if stall_resets >= 3:
                # 迭代8：放弃前最后一眼——屏幕可能已到目标（指纹误判"无变化"），LLM 复查一次
                try:
                    _last = last_chance_check(task, elems)
                except Exception:
                    _last = None
                if _last:
                    _m = _last
                    print("[agent] 最后一眼复查：任务其实已完成 → %s" % _m)
                    tracer.log(step, "done", _m)
                    tracer.close()
                    usage["qwen"] += 1
                    return 0
                _m = ("无法完成：已尝试 %d 步仍无进展（%s），判断这条路走不通，已停止。"
                      % (step, ",".join(flags) if flags else "重复动作/屏幕无变化"))
                print("[agent] 无进展兜底放弃：%s" % _m)
                tracer.log(step, "result", "无进展放弃(stall=%d)" % stall_resets)
                print("[agent] DONE: %s" % _m)
                tracer.log(step, "done", _m)
                tracer.close()
                if exec_log:
                    try:
                        save_failure(task, "无进展兜底放弃", exec_log,
                                     _stage="步进", _pattern="no_progress")
                    except Exception:
                        pass
                return 0
            print("[step %d] [reset] 连续无进展（%s）→ 注入迷路重置提示（第 %d/3 次）" %
                  (step, ",".join(flags) if flags else "-", stall_resets))
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
        # 有具体原因（熄屏/锁屏自救失败等）就用它；否则退回通用说明
        fail_reason = (result if isinstance(result, str) and result else
                       "portal 不可用（中止）")
        print("[agent] FAILED: %s" % fail_reason)
    else:
        fail_reason = "步数用尽（%d 步未完成）" % max_steps
        print("[agent] max steps (%d) reached, no done." % max_steps)
    if exec_log:
        _stage, _pattern, _evidence = "", "", ""
        if SL is not None:
            try:
                _open_fail = sum(1 for s in exec_log
                                 if str(s).startswith("open_app") and str(s).endswith("（失败）"))
                _stage, _pattern = SL.classify_failure({
                    "min_elems": min_elems_seen,
                    "plan_pkg": (plan or {}).get("app_package") or "",
                    "no_plan_app": bool(plan) and not (plan or {}).get("app_package"),
                    "max_block_streak": max_block_streak,
                    "open_app_fail": _open_fail,
                    "done_rejects": done_rejects,
                    "anchor_miss": anchor_miss,
                    "errs": errs,
                    "last_err": errs[-1] if errs else "",
                })
                _evidence = "|".join(errs[-3:])[:160]
            except Exception as e:
                print("[agent] 失败归类异常（忽略）: %r" % (e,))
        save_failure(task, fail_reason, exec_log, _stage, _pattern, _evidence)
        print("[agent] 失败教训已记录: %d 步（stage=%s pattern=%s）→ ~/bridge/skills/failures.json"
              % (len(exec_log), _stage or "-", _pattern or "-"))
        # 失败交还：把"卡在哪一关"明确报出来（控制台/对话页据此展示"重试 / 交给用户"）
        print("[agent] 卡点: stage=%s | pattern=%s | 步数=%d/%d"
              % (_stage or "未知", _pattern or "-", len(exec_log), max_steps))
    tracer.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
