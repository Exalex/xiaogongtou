#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wx_send_mobile.py — 手机本地"技能版"微信发消息 v3（root 运行，近零依赖：仅标准库）

v3.0 核心升级（2026-09-29 晚，针对"宽度≠身份"认错人事故）：
  · 身份确权取代宽度校验——
      已建档（有墨迹模板）→ 本地"标题墨迹网格"像素比对（~0.05s，实测同名人 0.0 差）
      未建档 → 视觉读"名单"（一次调用：谁在第几行）+ 视觉读"标题"（二次调用确认身份）
  · 找不到目标 = 干净停（0 点击 0 输入），不再"圈个宽度最像的"
  · 中止自动打扫（退回会话列表），并留终帧截图

流程（状态机 + 四道校验）:
  唤醒屏 → 打开微信 → 回列表 → [校验1:在列表（底部绿）]
  → 定位+身份确权（模板 或 视觉名单+标题）→ [校验2:身份]
  → 点输入框 → [键盘硬闸门] → 点真键盘打字 → [校验3:输入框有字/发送键]
  → 颜色定位发送键 → 点发送 → [校验4:送达（输入框清空+浅绿气泡）]
本地像素：截图 = screencap raw（~0.27s）· 点击 = input tap。
视觉调用（~12s/次）仅用于"首次建档"和"模板失效兜底"，全程计预算（最多 4 次）。
退出码: 0=成功 1=未回到列表 2=进错会话 3=输入/上屏失败 4=未找到发送键 5=送达失败 6=找不到目标 7=视觉超预算 9=内部异常
--json-out：结果 JSON（ok/reason/elapsed），供 agent/console 读取（"零静默错误"回执）。
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(line_buffering=True)   # 崩溃时输出不丢（agent 侧再用 -u 双保险）
except Exception:
    pass

W, H, HDR = 1080, 2400, 16
T0 = time.time()
JSON_OUT = ""
RESULT = {"ok": False, "reason": "未开始", "elapsed": 0.0, "stage": "init"}

# ---- 标题墨迹网格参数（2026-09-29 实测标定：同名 差=0.0；异名 差≥63）----
GW, GH = 96, 24                 # 网格尺寸
Y_T0, Y_T1 = 138, 208           # 标题带 y（避开状态栏）
X_T0, X_T1 = 150, 770           # 标题带 x（避开左徽标/右图标）
TPL_MEAN_MAX = 3.0              # 模板通过：平均绝对差上限
TPL_BIG_MAX = 0.02              # 模板通过：>50 差值格占比上限
VLM_MAX = 4                     # 单次运行视觉调用预算

# ---- 视觉模型（手机可达的局域网端点；与 mini_agent 同源）----
LLM_BASE = os.environ.get("LLM_BASE", "http://192.168.3.75:8888/v1")
LLM_KEY = os.environ.get("LLM_KEY", "123")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3.8-flash-next")
_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_VLM_N = [0]


def _clean_env():
    """剥离 Termux 的 LD_LIBRARY_PATH/LD_PRELOAD —— 否则系统二进制（screencap/input/am）
    在 agent（console root 上下文）里会 "CANNOT LINK EXECUTABLE ... libunwindstack" 输出 0 字节。"""
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    return env


def run(cmd, t=20):
    return subprocess.run(cmd, capture_output=True, timeout=t, env=_clean_env())


def tap(x, y):
    run(["/system/bin/input", "tap", str(x), str(y)], 15)


def shot():
    buf = run(["/system/bin/screencap"], 30).stdout
    if len(buf) < HDR + W * H * 4:
        raise RuntimeError("screencap 输出异常：%d 字节（期望≥%d；可能横屏或系统服务异常）"
                           % (len(buf), HDR + W * H * 4))
    return buf


def shot_png(path):
    """截 PNG 落盘（视觉调用用），返回 PNG bytes。"""
    run(["/system/bin/screencap", "-p", path], 30)
    with open(path, "rb") as f:
        return f.read()


def finish(code, reason, stage=""):
    RESULT.update({"ok": code == 0, "reason": reason, "stage": stage,
                   "elapsed": round(time.time() - T0, 2)})
    if JSON_OUT:
        try:
            os.makedirs(os.path.dirname(JSON_OUT), exist_ok=True)
        except Exception:
            pass
        try:
            with open(JSON_OUT, "w", encoding="utf-8") as f:
                json.dump(RESULT, f, ensure_ascii=False)
        except Exception:
            pass
    print("== %s：%s（耗时 %.2f 秒）==" % ("完成" if code == 0 else "中止", reason,
                                     RESULT["elapsed"]))
    sys.exit(code)


# ================================================================ 像素工具
def bottomtab_green(img):
    """底部导航栏绿色像素数（会话列表页独有特征：微信 tab 选中态为绿色）"""
    n = 0
    for y in range(2180, 2345, 3):
        base = HDR + y * W * 4
        for x in range(40, 1040, 4):
            off = base + x * 4
            r, g, b = img[off], img[off + 1], img[off + 2]
            if g > 140 and r < 130 and g - r > 50:
                n += 1
    return n


def est_span(text):
    """按渲染宽度估算像素跨度：ASCII ≈26px/字，中文 ≈43.5px/字（仅用于定位粗筛）"""
    w = 0.0
    for ch in text:
        w += 26.0 if ord(ch) < 128 else 43.5
    return w


def text_bands(img, y0=240, y1=2210, x0=100, x1=1010, gap=8):
    """检测列表中的"文字行带"（暗像素密排的行），返回 [(top, bottom, mid), ...]"""
    bands = []
    cur = None
    for y in range(y0, y1, 2):
        base = HDR + y * W * 4
        cnt = 0
        for x in range(x0, x1, 6):
            off = base + x * 4
            if img[off] + img[off + 1] + img[off + 2] < 330:
                cnt += 1
        dense = cnt > 3
        if dense and cur is None:
            cur = [y, y]
        elif dense and cur is not None:
            cur[1] = y
        elif not dense and cur is not None:
            if cur[1] - cur[0] >= gap:
                bands.append((cur[0], cur[1], (cur[0] + cur[1]) // 2))
            cur = None
    if cur is not None and cur[1] - cur[0] >= gap:
        bands.append((cur[0], cur[1], (cur[0] + cur[1]) // 2))
    return bands


def snap_to_band(img, y):
    """把模型给的 y 吸附到最近的文字行带中心（≤90px）；无邻近行带返回 None（宁可不点）。"""
    best = None
    bd = 10 ** 9
    for (_a, _b, mid) in text_bands(img):
        d = abs(mid - y)
        if d < bd:
            bd = d
            best = mid
    return best if (best is not None and bd <= 90) else None


def collect_window_bands(img, lo_w, hi_w, cap=4):
    """扫描列表里"文字跨度"落在 [lo_w, hi_w] 的行带（候选行），返回 [(y0,y1,span)]（上限 cap）。"""
    out = []
    for (y0, y1, _mid) in text_bands(img):
        lo = hi = None
        for y in range(y0, min(y1, y0 + 56) + 1, 4):
            base = HDR + y * W * 4
            for x in range(205, 800, 3):
                off = base + x * 4
                if img[off] + img[off + 1] + img[off + 2] < 330:
                    if lo is None or x < lo:
                        lo = x
                    if hi is None or x > hi:
                        hi = x
        span = (hi - lo) if lo is not None else 0
        print("    候选带 y=%d..%d span=%d（窗 %d-%d）" % (y0, y1, span, int(lo_w), int(hi_w)))
        if lo_w <= span <= hi_w:
            out.append((y0, y1, span))
            if len(out) >= cap:
                break
    return out


def dark_count(img, y, x0, x1, step=4, thr=115):
    n = 0
    base = HDR + y * W * 4
    for x in range(x0, x1, step):
        off = base + x * 4
        if img[off] + img[off + 1] + img[off + 2] < thr * 3:
            n += 1
    return n


def dark_count_region(img, y0, y1, x0, x1, step=4, thr=115):
    n = 0
    for y in range(y0, y1, 3):
        n += dark_count(img, y, x0, x1, step, thr)
    return n


def find_green(img, y0, y1, x0, x1):
    """深绿（发送键 #07C160 系）质心"""
    xs = ys = n = 0
    for y in range(y0, y1, 2):
        base = HDR + y * W * 4
        for x in range(x0, x1, 2):
            off = base + x * 4
            r, g, b = img[off], img[off + 1], img[off + 2]
            if g > 140 and r < 120 and b < 170 and g - r > 60:
                xs += x
                ys += y
                n += 1
    return (xs // n, ys // n, n) if n >= 20 else None


def find_bubble(img, y0, y1, x0, x1):
    """浅绿气泡（#95EC69 系）——注意与发送键的深绿不同，r 分量高"""
    n = 0
    for y in range(y0, y1, 2):
        base = HDR + y * W * 4
        for x in range(x0, x1, 2):
            off = base + x * 4
            r, g, b = img[off], img[off + 1], img[off + 2]
            if g > 200 and r > 120 and g - r > 40 and g - b > 80:
                n += 1
    return n


def find_candidate(img):
    """输入法第一候选（蓝色高亮块）中心——点它=精确提交组合文本。
    找不到返回 None（调用方不得盲点固定坐标）。"""
    xs = []
    ys = []
    for y in range(1540, 1630, 2):
        base = HDR + y * W * 4
        for x in range(40, 320, 2):
            off = base + x * 4
            r, g, b = img[off], img[off + 1], img[off + 2]
            if b > 200 and b - r > 50 and b - g > 30:
                xs.append(x)
                ys.append(y)
    if len(xs) >= 30:
        return sum(xs) // len(xs), sum(ys) // len(ys)
    return None


def kb_shown():
    """键盘是否真的弹出（输入法 mInputShown）——"确实在聊天输入状态"的硬闸门。"""
    r = run(["/system/bin/sh", "-c", "dumpsys input_method | grep -m1 mInputShown"], 10)
    return b"mInputShown=true" in (r.stdout or b"")


def screen_dark_ratio(img, y0=300, y1=1500):
    """列表区暗像素比例——微信"小程序下拉面板"是深色背景（实测 0.89），正常列表 0.05。"""
    dark = 0
    tot = 0
    for y in range(y0, y1, 30):
        base = HDR + y * W * 4
        for x in range(60, 1020, 30):
            off = base + x * 4
            if img[off] + img[off + 1] + img[off + 2] < 330:
                dark += 1
            tot += 1
    return dark / float(tot or 1)


def list_hash(img):
    s = 0
    for y in range(300, 1400, 40):
        base = HDR + y * W * 4
        for x in range(60, 1020, 40):
            off = base + x * 4
            s = (s * 31 + img[off] + img[off + 1] + img[off + 2]) & 0xFFFFFFFF
    return s


def scroll_list_to_top(img):
    """把会话列表滑回顶部并返回稳定帧（到顶标志=拉出深色「小程序面板」→ 必须显式关闭）。"""
    for i in range(5):
        h1 = list_hash(img)
        run(["/system/bin/input", "swipe", "540", "400", "540", "2000", "300"], 12)
        time.sleep(0.8)
        img2 = shot()
        if screen_dark_ratio(img2) > 0.4:
            print("    已到顶部（下拉拉出了小程序面板）")
            img = img2
            break
        if list_hash(img2) == h1:
            print("    列表已在顶部（滚不动了）")
            img = img2
            break
        img = img2
        print("    朝顶部滚动 %d 次" % (i + 1))
    for _ in range(2):
        if screen_dark_ratio(img) <= 0.4:
            break
        print("    关闭小程序面板")
        run(["/system/bin/input", "swipe", "540", "1500", "540", "700", "500"], 12)
        time.sleep(0.9)
        img = shot()
    time.sleep(0.3)
    return shot()


def back_to_list():
    """从任意页面退回会话列表（多位置试返回箭头 + 每次校验底部绿）。返回列表帧或 None。"""
    for attempt, (rx, ry) in enumerate(((80, 170), (110, 168), (58, 172), (135, 170)), 1):
        tap(rx, ry)
        time.sleep(0.7)
        img = shot()
        if bottomtab_green(img) > 40:
            return img
        print("    退回尝试 %d：tap(%d,%d) 未到列表" % (attempt, rx, ry))
    return None


# ================================================================ 标题墨迹网格（身份模板）
def title_grid(img):
    """标题带 → 墨迹网格。(grid_bytes, (lo,hi,tlo,thi)) 或 (None,None)。

    只对"标题文字"本身取紧凑包围盒（避开两侧徽标/图标），再归一化到 GW×GH 灰度网格。
    实测（2026-09-29）：同一标题跨运行 差=0.0；不同标题 差≥63。"""
    lo = hi = tlo = thi = None
    for y in range(Y_T0, Y_T1, 2):
        base = HDR + y * W * 4
        for x in range(X_T0, X_T1, 2):
            off = base + x * 4
            if img[off] + img[off + 1] + img[off + 2] < 330:
                if lo is None or x < lo:
                    lo = x
                if hi is None or x > hi:
                    hi = x
                if tlo is None or y < tlo:
                    tlo = y
                if thi is None or y > thi:
                    thi = y
    if lo is None or (hi - lo) < 30 or (thi - tlo) < 16:
        return None, None
    lo = max(0, lo - 2)
    hi = min(W, hi + 3)
    tlo = max(0, tlo - 2)
    thi = min(H, thi + 3)
    grid = bytearray(GW * GH)
    for gy in range(GH):
        sy = tlo + (thi - tlo) * gy // GH
        for gx in range(GW):
            sx = lo + (hi - lo) * gx // GW
            acc = n = 0
            for dy in range(3):
                yy = min(sy + dy, H - 1)
                for dx in range(3):
                    xx = min(sx + dx, W - 1)
                    off = HDR + yy * W * 4 + xx * 4
                    acc += (img[off] + img[off + 1] + img[off + 2]) // 3
                    n += 1
            grid[gy * GW + gx] = acc // n
    return bytes(grid), (lo, hi, tlo, thi)


def tpl_match(grid, tpl_b64):
    """墨迹网格与存档模板比对。返回 (ok, mean, big_ratio)。"""
    if not grid or not tpl_b64:
        return False, None, None
    try:
        tpl = base64.b64decode(tpl_b64)
    except Exception:
        return False, None, None
    if len(tpl) != len(grid):
        return False, None, None
    diff_sum = 0
    big = 0
    for a, b in zip(grid, tpl):
        d = abs(a - b)
        diff_sum += d
        if d > 50:
            big += 1
    mean = diff_sum / float(len(grid))
    ratio = big / float(len(grid))
    return (mean <= TPL_MEAN_MAX and ratio <= TPL_BIG_MAX), round(mean, 1), round(ratio, 3)


# ================================================================ 视觉（局域网多模态）
def vlm_chat(prompt, png_bytes, max_tokens=900):
    """一次视觉问答（截图→文字/JSON）。超预算返回 None。"""
    if _VLM_N[0] >= VLM_MAX:
        print("    视觉调用已达预算上限 %d" % VLM_MAX)
        return None
    _VLM_N[0] += 1
    t0 = time.time()
    b64 = base64.b64encode(png_bytes).decode()
    payload = {"model": LLM_MODEL, "temperature": 0, "max_tokens": max_tokens,
               "chat_template_kwargs": {"enable_thinking": False},
               "messages": [{"role": "user", "content": [
                   {"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]}]}
    req = urllib.request.Request(LLM_BASE.rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + LLM_KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with _OP.open(req, timeout=110) as resp:
            d = json.loads(resp.read())
        txt = (d["choices"][0]["message"].get("content") or "").strip()
    except Exception as e:
        print("    视觉调用失败：%r" % (e,))
        return None
    print("    视觉调用 #%d 用时 %.1fs" % (_VLM_N[0], time.time() - t0))
    return txt


def vlm_list_names(png, w, h):
    """读「会话名单」：返回 [(name, x, y), ...]（坐标已换算为像素；失败返回 []）。"""
    q = ("这是安卓微信的聊天会话列表截图，分辨率 %dx%d。列出图中所有会话条目："
         "每项给名称和该名称文字的中心坐标。只输出 JSON 数组，不要解释、不要代码块。"
         '每项形如 {"name":"名称","x":X,"y":Y}（X/Y 用 0-1000 归一化值）。最多 15 项。'
         % (w, h))
    txt = vlm_chat(q, png, 900)
    if not txt:
        return []
    print("    视觉名单原文：%s" % txt.replace("\n", " ")[:300])
    m = re.search(r"\[[\s\S]*\]", txt)
    items = []
    if m:
        try:
            items = json.loads(m.group(0))
        except Exception:
            try:
                items = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))
            except Exception:
                items = []
    ys = [it.get("y") for it in items
          if isinstance(it, dict) and isinstance(it.get("y"), (int, float))]
    if ys and max(ys) <= 1000:          # 归一化坐标 → 像素
        for it in items:
            for k, dim in (("x", w), ("y", h)):
                v = it.get(k)
                if isinstance(v, (int, float)):
                    it[k] = int(round(v * dim / 1000.0))
    out = []
    for it in items[:15]:
        try:
            nm = str(it.get("name") or "").strip()
            x, y = int(it.get("x")), int(it.get("y"))
        except Exception:
            continue
        if nm and 0 <= x <= w and 0 <= y <= h:
            out.append((nm, x, y))
    return out


def vlm_title(png):
    """读「标题栏文字」。失败返回 None。"""
    q = "这是安卓手机截图。请只回答屏幕顶部标题栏显示的文字内容，不要解释，只输出文字本身。"
    return vlm_chat(q, png, 64)


def norm_name(s):
    """名字归一化：去所有空白 + 全小写（大小写不敏感）。"""
    return re.sub(r"\s+", "", (s or "")).casefold()


# ================================================================ 联系人档案（宽度+墨迹模板）
CONTACTS = "/data/data/com.termux/files/home/bridge/wx_contacts.json"


def load_contacts():
    try:
        with open(CONTACTS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_contact(name, span, grid):
    """成功确权后记忆：宽度指纹（定位用）+ 墨迹模板（身份比对用）。"""
    try:
        d = load_contacts()
        rec = {"span": int(span), "ts": int(time.time())}
        if grid:
            rec["tpl"] = base64.b64encode(grid).decode()
        d[name.strip().lower()] = rec
        os.makedirs(os.path.dirname(CONTACTS), exist_ok=True)
        with open(CONTACTS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


# ================================================================ 键盘与打字
ROW1 = "qwertyuiop"
ROW2 = "asdfghjkl"
ROW3 = "zxcvbnm"


def key_pos(ch, first):
    """搜狗英文键盘键位。first=打第一个字母前（无候选栏）；之后候选栏出现，键盘下移 ~46px。"""
    y_off = 0 if first else 46
    if ch in ROW1:
        return (67 + ROW1.index(ch) * 105, 1712 + y_off)
    if ch in ROW2:
        return (118 + ROW2.index(ch) * 105, 1865 + y_off)
    if ch in ROW3:
        return (223 + ROW3.index(ch) * 105, 2018 + y_off)
    raise ValueError("目前仅支持英文小写字母（中文内容下一版支持），收到：%r" % ch)


def main():
    global JSON_OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--save", default="/data/local/tmp")
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()
    JSON_OUT = a.json_out
    txt = a.text.lower()
    bad = "".join(dict.fromkeys(ch for ch in txt if not ("a" <= ch <= "z")))
    if bad:
        # 用户友好文案（会直达通知栏）：先说清"支持什么"，再说"哪里不行"
        finish(11, "消息内容含中文或符号「%s」，目前只支持英文小写字母（如 test）"
                   "——这条没有发出去。" % bad[:6], "content")
    for ch in txt:
        key_pos(ch, True)  # 预检：内容必须全为小写字母

    RESULT.update({"to": a.to, "text": a.text})

    def mark(msg):
        print("[t+%6.2fs] %s" % (time.time() - T0, msg))

    # 0. 屏幕唤醒
    try:
        pw = run(["/system/bin/dumpsys", "power"], 10).stdout.decode("utf-8", "replace")
        if "mWakefulness=Awake" not in pw:
            run(["/system/bin/input", "keyevent", "224"], 8)  # KEYCODE_WAKEUP
            time.sleep(0.8)
            mark("屏幕已唤醒")
    except Exception:
        pass

    # 1. 打开微信（幂等）→ 等前台 → 退回会话列表 → [校验1:底部绿]
    run(["/system/bin/am", "start", "-n", "com.tencent.mm/.ui.LauncherUI"], 20)
    time.sleep(0.8)
    foc = False
    for _ in range(10):
        fg = run(["/system/bin/sh", "-c",
                  "dumpsys window displays | grep mCurrentFocus"], 10)
        if b"tencent.mm" in (fg.stdout or b""):
            foc = True
            break
        time.sleep(0.4)
    mark("微信已到前台=%s" % foc)
    time.sleep(0.4)
    img = back_to_list()
    if img is None:
        finish(1, "无法回到会话列表（手机可能锁屏/被占用；请解锁并保持亮屏后重试）", "list")
    open(a.save + "/wx1_list.raw", "wb").write(img)
    mark("已到会话列表（底部绿色=%d，截图1存档）" % bottomtab_green(img))

    # 2a. 列表滑回顶部（完成后校验：屏幕确实还停在会话列表——
    #     防"通知栏展开/他人操作/微信异常弹窗"在运行中途抢占屏幕导致在错画面上乱猜）
    img = scroll_list_to_top(img)
    mark("列表已回顶部区域")
    if bottomtab_green(img) < 40:
        open(a.save + "/wx5_end.raw", "wb").write(img)      # 留证：被抢占时的屏幕
        mark("警告：回顶后会话列表不可见（被抢占？）→ 尝试恢复，未恢复则干净退出")
        img2 = back_to_list()
        if img2 is None:
            finish(1, "扫描前屏幕不在会话列表（通知栏/他人操作/微信异常弹窗抢占；未点击）", "precheck")
        img = img2
        mark("屏幕被抢占后已恢复列表")

    # 2b. 定位 + 身份确权（v3 核心）
    ck = load_contacts().get(a.to.strip().lower()) or {}
    tpl = ck.get("tpl")
    located = False
    grid = None
    grid_bbox = None

    if tpl:
        # —— 路线 A（已建档）：宽度粗筛 → 点行 → 墨迹模板比对（本地，~0.05s）——
        span = ck.get("span") or int(est_span(a.to))
        mark("已建档：宽度指纹 %dpx + 墨迹模板" % span)
        lo_w, hi_w = span - 12, span + 12
        cands = collect_window_bands(img, lo_w, hi_w)
        if not cands:   # 指纹过期兜底：放宽到 ±25% 再扫一遍当前屏
            e = est_span(a.to)
            mark("紧窗无候选 → 放宽窗（±25%）重扫")
            cands = collect_window_bands(img, e * 0.75, e * 1.25)
        for i, (y0, y1, _sp) in enumerate(cands):
            y_click = (y0 + y1) // 2 + 28
            mark("候选 %d/%d：点击 y=%d" % (i + 1, len(cands), y_click))
            tap(540, y_click)
            time.sleep(1.1)
            img = shot()
            open(a.save + "/wx2_chat.raw", "wb").write(img)
            grid, grid_bbox = title_grid(img)
            ok, mean, ratio = tpl_match(grid, tpl)
            mark("模板比对：差=%s 大格比=%s → %s" % (mean, ratio, "通过" if ok else "不匹配"))
            if ok:
                located = True
                break
            img2 = back_to_list()
            if img2 is None:
                finish(1, "候选不匹配后无法回到列表（中止）", "list")
            img = img2
        if not located:
            mark("模板路线未命中 → 转视觉确权（兜底）")

    if not located:
        # —— 路线 B（首次/兜底）：视觉读「名单」（名字→行）→ 点行 → 视觉读「标题」确权 ——
        hit = None
        for attempt in (1, 2):
            img = shot()                                    # 与名单同帧（坐标吸附基准）
            png = shot_png(a.save + "/wx_vlm%d.png" % attempt)
            names = vlm_list_names(png, W, H)
            mark("名单第 %d 屏：读到 %d 条（视觉调用累计 %d/%d）" % (attempt, len(names), _VLM_N[0], VLM_MAX))
            want = norm_name(a.to)
            for (nm, _x, _y) in names:
                if norm_name(nm) == want:
                    hit = (nm, _x, _y)
                    break
            if hit:
                break
            if attempt == 1:
                mark("本屏名单没有「%s」→ 上滑翻一屏再看" % a.to)
                run(["/system/bin/input", "swipe", "540", "1500", "540", "800", "280"], 12)
                time.sleep(0.9)
                img = shot()
        if not hit:
            img2 = back_to_list() or img
            open(a.save + "/wx5_end.raw", "wb").write(img2)
            finish(6, "名单里没有「%s」：可能名字不同/不在会话里（0 点击 0 输入，已回列表）" % a.to,
                   "locate")
        nm, mx, my = hit
        # 坐标吸附：模型 y → 最近文字行带（防坐标体系歧义；吸不到就不点）
        y_snap = snap_to_band(img, my)
        if y_snap is None:
            back_to_list()
            finish(6, "名单命中「%s」但坐标无法落到行上（防误点，中止）" % nm, "locate")
        mark("名单命中「%s」(模型 y=%d → 吸附行 y=%d)，点击进入" % (nm, my, y_snap))
        tap(540, y_snap)
        time.sleep(1.2)
        img = shot()
        open(a.save + "/wx2_chat.raw", "wb").write(img)
        # 标题确权：已建档 → 本地墨迹模板（快；省掉一次 ~10-18s 的视觉读标题）；
        # 未建档 / 模板不过 → 视觉读标题；两者都不过 → 干净退出，绝不输入
        grid, grid_bbox = title_grid(img)
        ok_tpl = False
        if tpl:
            ok_tpl, mean2, ratio2 = tpl_match(grid, tpl)
            mark("模板比对(兜底)：差=%s 大格比=%s → %s"
                 % (mean2, ratio2, "通过" if ok_tpl else "不匹配"))
        if not ok_tpl:
            t = vlm_title(shot_png(a.save + "/wx_vlm_title.png"))
            mark("标题读回：%r（目标：%r）" % (t, a.to))
            if t is None:
                back_to_list()
                finish(7, "标题确权失败：视觉读取无输出（未输入；已回列表）", "identity")
            if norm_name(t) != norm_name(a.to):
                img2 = back_to_list() or img
                open(a.save + "/wx5_end.raw", "wb").write(img2)
                finish(2, "进错会话：标题是「%s」≠「%s」（未输入任何内容，已回列表）" % (t, a.to),
                       "identity")
        # 确权通过 → 存档/刷新身份模板（下次本地秒验）
        if grid and grid_bbox:
            save_contact(a.to, grid_bbox[1] - grid_bbox[0], grid)
            mark("已存档「%s」身份模板（宽度 %dpx；下次更快）" % (a.to, grid_bbox[1] - grid_bbox[0]))
        else:
            mark("确权通过，但标题网格不可用（跳过存档）")

    # 3. 点输入框 → [键盘硬闸门] → 打字
    tap(540, 2280)
    time.sleep(1.4)
    if not kb_shown():
        mark("键盘未出现，重点一次输入框")
        tap(540, 2280)
        time.sleep(1.2)
    if not kb_shown():
        back_to_list()
        finish(3, "键盘未弹出（不是聊天输入状态，未输入任何内容）", "input")
    mark("键盘已弹出（输入态确认）")
    for i, ch in enumerate(txt):
        x, y = key_pos(ch, i == 0)
        tap(x, y)
        time.sleep(0.42)
    time.sleep(0.3)
    img = shot()
    open(a.save + "/wx3_typed.raw", "wb").write(img)

    # 3b. 上屏校验 + 组合态提交
    def send_key(im):
        g0 = find_green(im, 1330, 1500, 850, 1070)
        return g0 if (g0 and 1500 <= g0[2] <= 3600) else None

    g = send_key(img)
    if not g:
        cand = find_candidate(img)
        if cand:
            mark("发送键未出现 → 组合态：点首候选 (%d,%d)" % cand)
            tap(cand[0], cand[1])
            time.sleep(0.9)
            img = shot()
            open(a.save + "/wx3b_commit.raw", "wb").write(img)
            g = send_key(img)
            if not g and kb_shown():
                mark("退路：点空格键 (537,2140)")
                tap(537, 2140)
                time.sleep(0.9)
                img = shot()
                open(a.save + "/wx3c_space.raw", "wb").write(img)
                g = send_key(img)
        else:
            mark("发送键未出现且无候选高亮 → 不盲点，中止")
    if not g:
        finish(3, "输入未上屏/未能提交（未点发送）", "type")
    mark("输入已上屏（发送键就绪）")

    # 4. 颜色定位发送键 → 点击
    gx, gy, gn = g
    mark("发送键质心 (%d,%d) 绿像素=%d" % (gx, gy, gn))
    tap(gx, gy)
    time.sleep(1.3)

    # 5. 校验送达
    img = shot()
    open(a.save + "/wx4_sent.raw", "wb").write(img)
    cnt2 = dark_count_region(img, 1390, 1480, 150, 800, step=3)
    bubble = find_bubble(img, 300, 1360, 80, 1040)
    mark("送达校验：输入框残留=%d（应≤40）· 消息区浅绿像素=%d（应>300）" % (cnt2, bubble))
    if cnt2 > 40 or bubble < 300:
        finish(5, "送达校验未通过（请人工核对 wx4_sent.raw）", "deliver")
    finish(0, "已送达 %s「%s」" % (a.to, a.text), "deliver")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as e:
        import traceback
        traceback.print_exc()
        finish(9, "技能内部异常：%r" % (e,), "exc")
