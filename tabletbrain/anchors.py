#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""anchors.py — 三级锚点（"确定性判定"的地基）

背景（2026-10-11）：
  系统的验收/页面身份判定过去全部依赖"屏幕文字"，而屏幕文字已被多次证明不可靠——
  a11y 树有深度/长度截断、榜单序号是自绘图形、微信整树被屏蔽、FLAG_SECURE 页面截图全黑。
  本模块提供三级锚点，硬优先：

    L1 硬  包名 / Activity 名     —— dumpsys 直读，不依赖界面怎么画
    L2 中  像素指纹（标题墨迹网格）—— 实测：同一页差 0.0 / 不同页 ≥63
    L3 软  屏幕文字特征词          —— 兜底，需 ≥2 个命中才算通过

  判定为 OR 语义（任一命中即通过），但**信度不同**，用于遥测（锚点级别分布）。

依赖：纯标准库（无 PIL —— 本机 Termux 实测无 PIL；截图走 `screencap` raw RGBA，
      与已跑通的 wx_send_mobile.py 同源，约 0.27s/次）。

CLI（标定工具）：
  python3 anchors.py fp [--pkg com.sina.weibo] [--page 发现页]
      → 截当前屏 → 打印指纹 JSON（供写进 apps.json 的 pages[].fingerprint）
  python3 anchors.py act      → 打印当前 包名/Activity
"""
import json
import os
import re
import subprocess
import sys

# ---- 标题墨迹网格参数（沿用 wx_send v3.0 实测标定：同名 差=0.0；异名 差≥63）----
GW, GH = 96, 24                    # 网格尺寸
Y_T0, Y_T1 = 138, 208              # 标题带 y（避开状态栏）
X_T0, X_T1 = 150, 770              # 标题带 x（避开左徽标 / 右图标）
FP_MEAN_MAX = 3.0                  # 指纹通过：平均绝对差上限
FP_BIG_MAX = 0.02                  # 指纹通过：>50 差值格占比上限
FP_BIG_DELTA = 50                  # "大格"判定阈值
TEXT_MIN = 2                       # L3 文本锚点：至少命中几个（锚点不足时自动降为可用数量）

HDR = 16                           # screencap raw 头长度（w/h/format/colorspace）
DEFAULT_W, DEFAULT_H = 1080, 2400


def _clean_env():
    """剥离 Termux 的 LD_LIBRARY_PATH/LD_PRELOAD —— 否则系统二进制（screencap/dumpsys）
    在 agent（console root 上下文）里会 CANNOT LINK 或输出 0 字节。"""
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


# ================================================================ L2 · 像素指纹
def raw_dims(buf):
    """从 screencap raw 头解析 (w, h)；异常时回退默认分辨率。"""
    try:
        if len(buf) >= HDR:
            w = int.from_bytes(buf[0:4], "little")
            h = int.from_bytes(buf[4:8], "little")
            if 64 <= w <= 8192 and 64 <= h <= 8192:
                return w, h
    except Exception:
        pass
    return DEFAULT_W, DEFAULT_H


def capture_raw(dpy=0, timeout=30):
    """截屏 raw（RGBA）。dpy>0 时加 -d N（注：本 ROM 的 screencap -d 抓不了虚拟屏 → 返回 None）。
    返回 bytes 或 None。"""
    cmd = ["/system/bin/screencap"]
    if dpy and dpy > 0:
        cmd += ["-d", str(int(dpy))]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=_clean_env())
        buf = r.stdout or b""
        if len(buf) < HDR + 64:
            return None
        return buf
    except Exception:
        return None


def fingerprint(raw, band=None):
    """raw RGBA → 标题墨迹网格（bytes，长度 GW*GH）。
    只对"标题文字"本身取紧凑包围盒（避开两侧徽标/图标），再归一化到 GW×GH 灰度网格。
    返回 bytes 或 None（找不到足够墨迹 / 数据不足）。"""
    if not raw or len(raw) < HDR + 64:
        return None
    w, h = raw_dims(raw)
    if len(raw) < HDR + w * h * 4:
        return None
    x0, x1, y0, y1 = band or (X_T0, X_T1, Y_T0, Y_T1)
    x0 = max(0, min(int(x0), w - 1))
    x1 = max(x0 + 1, min(int(x1), w))
    y0 = max(0, min(int(y0), h - 1))
    y1 = max(y0 + 1, min(int(y1), h))

    lo = hi = tlo = thi = None
    for y in range(y0, y1, 2):
        base = HDR + y * w * 4
        for x in range(x0, x1, 2):
            off = base + x * 4
            if raw[off] + raw[off + 1] + raw[off + 2] < 330:
                if lo is None or x < lo:
                    lo = x
                if hi is None or x > hi:
                    hi = x
                if tlo is None or y < tlo:
                    tlo = y
                if thi is None or y > thi:
                    thi = y
    if lo is None or (hi - lo) < 30 or (thi - tlo) < 16:
        return None
    lo = max(0, lo - 2)
    hi = min(w, hi + 3)
    tlo = max(0, tlo - 2)
    thi = min(h, thi + 3)

    grid = bytearray(GW * GH)
    for gy in range(GH):
        sy = tlo + (thi - tlo) * gy // GH
        for gx in range(GW):
            sx = lo + (hi - lo) * gx // GW
            acc = n = 0
            for dy in range(3):
                yy = min(sy + dy, h - 1)
                for dx in range(3):
                    xx = min(sx + dx, w - 1)
                    off = HDR + yy * w * 4 + xx * 4
                    acc += (raw[off] + raw[off + 1] + raw[off + 2]) // 3
                    n += 1
            grid[gy * GW + gx] = acc // n
    return bytes(grid)


def fp_distance(a, b):
    """两个指纹网格的距离 → (mean, big_ratio)；不可比时返回 (None, None)。"""
    if not a or not b or len(a) != len(b):
        return None, None
    diff_sum = 0
    big = 0
    for x, y in zip(a, b):
        d = abs(x - y)
        diff_sum += d
        if d > FP_BIG_DELTA:
            big += 1
    n = float(len(a))
    return round(diff_sum / n, 1), round(big / n, 3)


def fp_ok(a, b, mean_max=FP_MEAN_MAX, big_max=FP_BIG_MAX):
    """指纹是否匹配（同一页）。"""
    m, r = fp_distance(a, b)
    if m is None:
        return False
    return m <= mean_max and r <= big_max


def fp_to_json(grid):
    """指纹 → 可写进 JSON 的 list[int]（紧凑）。"""
    return list(grid) if grid else None


def fp_from_json(v):
    """JSON 里的指纹 → bytes（兼容 list[int] / 十六进制串 / base64 串）。"""
    if not v:
        return None
    try:
        if isinstance(v, (bytes, bytearray)):
            return bytes(v)
        if isinstance(v, list):
            return bytes(int(x) & 0xFF for x in v)
        if isinstance(v, str):
            s = v.strip()
            if re.fullmatch(r"[0-9a-fA-F]+", s) and len(s) == GW * GH * 2:
                return bytes.fromhex(s)
            import base64
            b = base64.b64decode(s)
            return b if len(b) == GW * GH else None
    except Exception:
        return None
    return None


# ================================================================ L1 · 包名 / Activity
def _norm_act(pkg, act):
    """把 dumpsys 里的简写 Activity 补全：com.a.b/.Main → com.a.b.Main"""
    if not act:
        return ""
    act = act.strip()
    if act.startswith("."):
        return (pkg or "") + act
    return act


def current_activity(dpy=0, timeout=8):
    """当前前台 包名/Activity（如 com.sina.weibo/com.sina.weibo.MainActivity）。
    解析 dumpsys window displays；取不到返回 ""。"""
    try:
        r = subprocess.run(["/system/bin/dumpsys", "window", "displays"],
                           capture_output=True, text=True, timeout=timeout, env=_clean_env())
        out = r.stdout or ""
    except Exception:
        return ""
    cur = None
    pkg = act = ""
    for ln in out.splitlines():
        m = re.search(r"Display: mDisplayId=(\d+)", ln)
        if m:
            if cur == dpy and (pkg or act):
                return ("%s/%s" % (pkg, act)) if act else pkg
            cur = int(m.group(1))
            pkg = act = ""
            continue
        if cur != dpy:
            continue
        # mCurrentFocus 优先（通常是全名）
        m1 = re.search(r"mCurrentFocus=Window\{[^}]*?\bu0\s+([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)", ln)
        if m1 and not act:
            pkg, act = m1.group(1), _norm_act(m1.group(1), m1.group(2))
            continue
        m2 = re.search(r"mFocusedApp=ActivityRecord\{[^}]*?\bu0\s+([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)", ln)
        if m2 and not act:
            pkg, act = m2.group(1), _norm_act(m2.group(1), m2.group(2))
    if cur == dpy and (pkg or act):
        return ("%s/%s" % (pkg, act)) if act else pkg
    return ""


def activity_match(want, act):
    """L1 匹配：want 可写全名（pkg/Activity）、简写（pkg/.Main）或仅包名。"""
    if not want or not act:
        return False
    w = str(want).strip()
    a = str(act).strip()
    if w == a or w.lower() == a.lower():
        return True
    # 简写补全后比较
    pkg = a.split("/", 1)[0]
    if w.startswith("."):
        w = pkg + w
        return w.lower() == a.lower()
    if "/" not in w:
        return pkg.lower() == w.lower()
    # want 含 "/" 且是简写
    wp, _, wa = w.partition("/")
    if wa.startswith("."):
        wa = wp + wa
    return (wp.lower() == pkg.lower() and wa.lower() == a.split("/", 1)[-1].lower())


# ================================================================ 三级锚点判定
def anchor_level(anchors, elems=None, act="", fp=None):
    """命中级别："L1" / "L2" / "L3" / ""（未命中）。用于遥测与调试。"""
    if not anchors:
        return ""
    if anchors.get("activity") and activity_match(anchors["activity"], act):
        return "L1"
    ref = fp_from_json(anchors.get("fingerprint"))
    if ref and fp and fp_ok(fp, ref):
        return "L2"
    ver = anchors.get("text")
    if ver is None:
        ver = anchors.get("verify")
    if isinstance(ver, dict):                        # {"verify": {"text": [...]}} 形式
        ver = ver.get("text") or []
    if isinstance(ver, str):
        ver = [ver]
    texts = [str(t) for t in (ver or []) if t]
    if texts and elems:
        labels = "|".join(str(e[3]) for e in elems)
        hits = sum(1 for t in texts if t in labels)
        if hits >= min(TEXT_MIN, len(texts)):
            return "L3"
    return ""


def verify_anchors(anchors, elems=None, act="", fp=None):
    """三级锚点是否命中（OR 语义，硬优先）。兼容两种写法：
      {"activity": "...", "fingerprint": [...], "text": ["词1","词2"]}
      {"verify": ["词1","词2"]}          # 纯文本（旧格式）
      ["词1","词2"]                       # 裸列表（最旧格式）
    """
    if not anchors:
        return False
    if isinstance(anchors, (list, tuple)):
        anchors = {"text": list(anchors)}
    if not isinstance(anchors, dict):
        return False
    return anchor_level(anchors, elems, act, fp) != ""


# ================================================================ CLI（标定工具）
def _main(argv):
    cmd = argv[0] if argv else "fp"
    dpy = 0
    band = None
    pkg = page = ""
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--display" and i + 1 < len(argv):
            dpy = int(argv[i + 1]); i += 2; continue
        if a == "--pkg" and i + 1 < len(argv):
            pkg = argv[i + 1]; i += 2; continue
        if a == "--page" and i + 1 < len(argv):
            page = argv[i + 1]; i += 2; continue
        i += 1

    if cmd == "act":
        act = current_activity(dpy)
        print(json.dumps({"activity": act}, ensure_ascii=False))
        return 0

    raw = capture_raw(dpy)
    if not raw:
        print(json.dumps({"ok": False, "reason": "截图失败（FLAG_SECURE 或 -d 虚拟屏不支持）"},
                         ensure_ascii=False))
        return 1
    w, h = raw_dims(raw)
    g = fingerprint(raw, band)
    if not g:
        print(json.dumps({"ok": False, "reason": "标题带未找到足够墨迹",
                          "size": [w, h]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "pkg": pkg, "page": page, "size": [w, h],
                      "activity": current_activity(dpy),
                      "fingerprint": fp_to_json(g)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
