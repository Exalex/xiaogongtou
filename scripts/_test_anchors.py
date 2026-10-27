#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_test_anchors.py — anchors.py 离线单测（0 网络 0 设备）

用合成的 raw RGBA 缓冲验证像素指纹与三级锚点判定；dumpsys 相关只测纯函数 activity_match。
跑法：python3 scripts/_test_anchors.py
"""
import sys

import anchors as A

HDR = A.HDR


def mk_raw(w, h, rects):
    """合成 screencap raw（RGBA，白底 + 若干深色矩形）"""
    buf = bytearray(HDR + w * h * 4)
    buf[0:4] = w.to_bytes(4, "little")
    buf[4:8] = h.to_bytes(4, "little")
    for i in range(HDR, len(buf), 4):
        buf[i] = 255
        buf[i + 1] = 255
        buf[i + 2] = 255
        buf[i + 3] = 255
    for (x0, y0, x1, y1, val) in rects:
        for y in range(y0, y1):
            base = HDR + y * w * 4
            for x in range(x0, x1):
                o = base + x * 4
                buf[o] = val
                buf[o + 1] = val
                buf[o + 2] = val
    return bytes(buf)


OK = True


def chk(name, cond):
    global OK
    print("%-46s %s" % (name, "PASS" if cond else "FAIL"))
    OK = OK and bool(cond)


W, H = 300, 120
BAND = (10, 250, 10, 70)

raw_a = mk_raw(W, H, [(20, 20, 180, 60, 0)])                       # 一条横条
raw_b = mk_raw(W, H, [(20, 20, 180, 60, 0)])                       # 同 A
raw_c = mk_raw(W, H, [(20, 20, 90, 60, 0), (110, 20, 180, 60, 0)])  # 两条（内部结构不同）
raw_blank = mk_raw(W, H, [])                                        # 全白

chk("raw_dims 解析", A.raw_dims(raw_a) == (W, H))

ga = A.fingerprint(raw_a, BAND)
gb = A.fingerprint(raw_b, BAND)
gc = A.fingerprint(raw_c, BAND)
chk("指纹 A 可用", ga is not None and len(ga) == A.GW * A.GH)
chk("空白图 → 无指纹", A.fingerprint(raw_blank, BAND) is None)
chk("数据不足 → 无指纹", A.fingerprint(b"\x00" * 10, BAND) is None)

m_ab, r_ab = A.fp_distance(ga, gb)
m_ac, r_ac = A.fp_distance(ga, gc)
chk("同图 差=0.0", m_ab == 0.0)
chk("异图 差明显更大", (m_ac or 0) > (m_ab or 0) + 10)
chk("fp_ok 同图 True", A.fp_ok(ga, gb))
chk("fp_ok 异图 False", not A.fp_ok(ga, gc))
chk("fp_distance 长度不符", A.fp_distance(ga, (ga or b"")[:10]) == (None, None))

j = A.fp_to_json(ga)
chk("指纹 JSON 往返", A.fp_from_json(j) == ga)
chk("指纹 hex 往返", A.fp_from_json(ga.hex()) == ga)
chk("指纹 非法输入 → None", A.fp_from_json("不是指纹") is None and A.fp_from_json(None) is None)

# ---- L1 activity 匹配 ----
chk("act 全名精确", A.activity_match("com.sina.weibo/com.sina.weibo.MainActivity",
                                     "com.sina.weibo/com.sina.weibo.MainActivity"))
chk("act 简写补全", A.activity_match("com.sina.weibo/.MainActivity",
                                    "com.sina.weibo/com.sina.weibo.MainActivity"))
chk("act 仅包名", A.activity_match("com.sina.weibo", "com.sina.weibo/com.sina.weibo.MainActivity"))
chk("act 不同包不匹配", not A.activity_match("com.tencent.mm",
                                             "com.sina.weibo/com.sina.weibo.MainActivity"))
chk("act 空不匹配", not A.activity_match("", "com.a/b") and not A.activity_match("com.a/b", ""))

# ---- 三级锚点 ----
elems = [(0, 100, 100, "实时热点", False), (1, 200, 200, "热搜榜", True)]
ACT = "com.sina.weibo/com.sina.weibo.MainActivity"

chk("L1 命中", A.anchor_level({"activity": "com.sina.weibo/.MainActivity"}, elems, ACT) == "L1")
chk("L1 优先于 L3",
    A.anchor_level({"activity": "com.sina.weibo", "text": ["实时热点"]}, elems, ACT) == "L1")
chk("L2 命中", A.anchor_level({"fingerprint": j}, elems, "", ga) == "L2")
chk("L2 不匹配", A.anchor_level({"fingerprint": j}, elems, "", gc) == "")
chk("L3 双词命中", A.anchor_level({"text": ["实时热点", "热搜榜"]}, elems, "") == "L3")
chk("L3 单词不足", A.anchor_level({"text": ["实时热点", "不存在"]}, elems, "") == "")
chk("L3 单词锚点放宽为 1", A.anchor_level({"text": ["实时热点"]}, elems, "") == "L3")
chk("verify 子字典形式", A.anchor_level({"verify": {"text": ["实时热点", "热搜榜"]}}, elems, "") == "L3")
chk("全部不中", A.anchor_level({"activity": "com.other", "text": ["无关词"]}, elems, ACT) == "")

chk("verify_anchors 裸列表", A.verify_anchors(["热搜榜"], elems))
chk("verify_anchors 字典", A.verify_anchors({"text": ["实时热点", "热搜榜"]}, elems))
chk("verify_anchors 空", not A.verify_anchors({}, elems))
chk("verify_anchors None", not A.verify_anchors(None, elems))

print("\n%s" % ("全部通过" if OK else "有失败项"))
sys.exit(0 if OK else 1)
