#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wx_intent.py — "给谁发消息"意图解析（console 与 agent 共用的单一事实来源）

只认明确句式，宁缺毋滥（误路由 = 盲操作微信 = 灾难）：
  0. 前缀噪声清理：语音口癖/客套词（呃/嗯/那个/帮我/请…）先削掉 —— 2026-10-01 新增，
     起因："呃，发条微信给EXLEX test"因开头"呃，"整句失配、没走技能直通（25 步空转）
  1. 发给X Y / 发微信给X：Y           —— 需分隔符
  2. 给X发(条/个/一)(微信/消息/信息)Y —— 微信/消息等关键词
  3. 给X发：Y / 给X发 Y               —— 需分隔符
  4. 给X发Y（连写，text≥2 且不以 表/布/举/声 开头）—— 兜底

返回 (to, text)；不满足则 None。两段均做去空白/引号处理。
"""
import re

_PATS = (
    r"^发(?:一)?(?:条|个)?(?:微信|消息|信息)?\s*给\s*(?P<to>.{1,24}?)\s*[：:，,、\s]+\s*(?P<text>.{1,200})$",
    r"^给\s*(?P<to>.{1,24}?)\s*发(?:一)?(?:条|个)?\s*(?:微信|消息|信息)\s*[：:，,、\s]*\s*(?P<text>.{1,200})$",
    r"^给\s*(?P<to>.{1,24}?)\s*发\s*[：:，,、\s]+\s*(?P<text>.{1,200})$",
    r"^给\s*(?P<to>.{1,24}?)\s*发\s*(?P<text>.{2,200})$",
)

# 连写兜底模式的护栏：常见非"发消息"词首字（如"发表意见/发布/举报"）
_BARE_BLOCK = set("表布举声")

# 代词护栏：语音口误/指代（"给那个发…"）不构成有效收件人 ——
# 这类输入两种处置：①路由层直接拒绝并提示"说清名字"（0 点击 0 输入）；
# ②绝不能当作真实联系人去列表里"找最像的"（防认错人）。
PRONOUNS = {"那个", "这个", "他", "她", "它", "他们", "她们", "它们",
            "对方", "某人", "那位", "这位", "人家", "ta"}


def is_pronoun(s):
    """收件人是纯代词（无指向）→ True。"""
    return (s or "").strip().lower() in PRONOUNS


# —— 前缀噪声词（语音口癖/客套；只削头部、不碰正文；不含"给/发"等结构词）——
_LEAD_NOISE = ("请帮我", "麻烦你", "帮我", "帮忙", "麻烦", "请",
               "那个", "然后", "我想", "我要", "我",
               "呃", "嗯", "啊", "哦", "噢", "哎", "哎呀", "唉", "诶", "喂", "嗨")


def strip_lead_noise(t):
    """削掉句首的语气词/客套词链："呃，发条微信给X test" → "发条微信给X test"。
    最多 4 轮（防"那个，帮我给…"这类叠加）；不会清空整句；不改动正文。"""
    for _ in range(4):
        s = t.lstrip(" \u3000\t，,、；;：:。")
        hit = None
        for w in sorted(_LEAD_NOISE, key=len, reverse=True):
            if s.startswith(w):
                hit = w
                break
        if not hit:
            return s
        s2 = s[len(hit):].lstrip(" \u3000\t，,、；;：:。")
        if not s2:          # 整句都是噪声词 → 原样返回（交给后续模式判定）
            return s
        t = s2
    return t


def parse_send_intent(task):
    """task → (to, text) 或 None。"""
    t = (task or "").strip()
    # 去尾部标点（"给exalex发 test。" → 去掉句号）
    t = re.sub(r"[。！!？?]+$", "", t)
    # 削句首语音口癖/客套（"呃，发条微信给X test" → "发条微信给X test"）
    t = strip_lead_noise(t)
    if not t or len(t) > 260:
        return None
    for i, p in enumerate(_PATS):
        m = re.match(p, t)
        if not m:
            continue
        to = m.group("to").strip(" \u3000\t：:，,、,;；\"'“”‘’.")
        tx = m.group("text").strip(" \u3000\t\"'“”‘’")
        if not to or not tx:
            continue
        if i == 3 and tx[0] in _BARE_BLOCK:   # 连写模式护栏
            continue
        return to, tx
    return None


if __name__ == "__main__":
    import sys
    cases = [
        # —— 回归（原有）——
        "给exalex发 test", "给 exalex 发条微信 hello", "给exalex发test",
        "发给exalex test", "发微信给 exalex：hello", "给 hao —— 每日任务 发 test",
        "给张三发表意见", "给电池充电", "去微博找热搜前五", "给exalex发微信：test2",
        # —— 新增：语音噪声前缀（2026-10-01 事故回归）——
        "呃，发条微信给EXLEX test",
        "嗯，给 exalex 发条微信 hello",
        "那个，帮我给exalex发 test",
        "麻烦给exalex发条消息：test",
        "我想给exalex发test",
    ]
    bad = 0
    for c in cases:
        r = parse_send_intent(c)
        print("%-30s -> %s" % (c, r))
    # 硬断言（新事故样本必须命中）
    assert parse_send_intent("呃，发条微信给EXLEX test") == ("EXLEX", "test"), "case1"
    assert parse_send_intent("嗯，给 exalex 发条微信 hello") == ("exalex", "hello"), "case2"
    assert parse_send_intent("那个，帮我给exalex发 test") == ("exalex", "test"), "case3"
    assert parse_send_intent("给张三发表意见") is None, "guard1"
    assert parse_send_intent("去微博找热搜前五") is None, "guard2"
    print("all assert OK")
