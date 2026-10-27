# -*- coding: utf-8 -*-
"""_vision_probe.py — 视觉闭环探针：截图 → 多模态模型给坐标 → 真的点下去 → 再截图验证。

用途：验证「a11y 树被屏蔽的 App（如微信）能否改走截图+视觉」这条路线。
用法：
  python _vision_probe.py list            # 只看模型给的元素清单（不点）
  python _vision_probe.py tap "<元素文字>"  # 让模型定位后点击，并前后截图对比
说明：走 portal HTTP（192.168.3.170:8080），需要 PORTAL_TOKEN；绕系统代理。
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request

PORTAL = os.environ.get("PORTAL_BASE", "http://192.168.3.170:8080")
TOK = os.environ.get("PORTAL_TOKEN", "")
LLM = os.environ.get("LLM_BASE", "http://192.168.3.75:8888/v1")
LKEY = os.environ.get("LLM_KEY", "123")
MODEL = os.environ.get("LLM_MODEL", "qwen3.8-flash-next")
OUT = os.environ.get("OUTDIR", "logs/wechat_test/vision")

_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def portal(path, payload=None, raw=False, timeout=40):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(PORTAL + path, data=data, method="POST" if data else "GET")
    r.add_header("Authorization", "Bearer " + TOK)
    if data:
        r.add_header("Content-Type", "application/json")
    with _OP.open(r, timeout=timeout) as resp:
        body = resp.read()
    return body if raw else json.loads(body)


def shot(tag):
    """portal /screenshot 返回 JSON（result = base64），需解码后落盘。"""
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, tag + ".png")
    raw = portal("/screenshot", raw=True)
    data = raw
    if raw[:1] == b"{":
        d = json.loads(raw)
        v = d.get("result", d)
        if isinstance(v, str):
            data = base64.b64decode(v)
    with open(p, "wb") as f:
        f.write(data)
    return p


def vlm(png, question):
    b64 = base64.b64encode(open(png, "rb").read()).decode()
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
        ]}],
        "temperature": 0, "max_tokens": 2000,
        # 必须关思考：开启时偶发"思维链吃光 token → content 为空"（实测 3 次里 1 次）
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = urllib.request.Request(LLM.rstrip("/") + "/chat/completions",
                               data=json.dumps(payload).encode(), method="POST")
    r.add_header("Authorization", "Bearer " + LKEY)
    r.add_header("Content-Type", "application/json")
    try:
        with _OP.open(r, timeout=180) as resp:
            d = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print("HTTP %s: %s" % (e.code, e.read()[:400].decode("utf-8", "replace")))
        raise
    return d["choices"][0]["message"].get("content") or ""


Q = ("这是安卓手机截图，分辨率 1080x2400（宽 x 高）。列出屏幕上所有可点击元素的中心坐标。"
     "只输出 JSON 数组，不要解释、不要代码块。"
     "每项形如 {\"label\":\"元素上的文字\",\"x\":X像素,\"y\":Y像素}。最多 30 项。")

Q2 = ("看图，输出 JSON 数组（只输出数组本身）：屏幕上可点击元素的文字与中心像素坐标，"
      "格式 [{\"label\":\"文字\",\"x\":0,\"y\":0}]。图片宽 1080 高 2400。")


def parse_items(txt):
    m = re.search(r"\[[\s\S]*\]", txt)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))
        except Exception:
            return []


def norm_xy(items, w, h):
    """模型输出的坐标可能是 像素 或 0–1000 归一化（实测两种都出现过）→ 统一成像素。

    判定：若全部 y ≤ 1000 且 h > 1000，则按归一化处理；否则原样。
    """
    ys = [it.get("y", 0) for it in items if isinstance(it.get("y"), (int, float))]
    if ys and max(ys) <= 1000 and h > 1200:
        for it in items:
            for k, dim in (("x", w), ("y", h)):
                v = it.get(k)
                if isinstance(v, (int, float)):
                    it[k] = int(round(v * dim / 1000.0))
    return items


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    before = shot("before")
    print("截图:", before)
    raw = vlm(before, Q)
    items = parse_items(raw)
    if not items:
        print("首次解析为空，重试一次（更短指令）… 首答长度=%d" % len(raw))
        raw = vlm(before, Q2)
        items = parse_items(raw)
    if not items:
        print("仍无结果，原始返回：", raw[:400])
    try:
        from PIL import Image
        w, h = Image.open(before).size
    except Exception:
        w, h = 1080, 2400
    items = norm_xy(items, w, h)
    print("模型给出可点元素 %d 个（已按 %dx%d 归一）：" % (len(items), w, h))
    for it in items:
        print("  (%4s,%5s) %-22s %s" % (it.get("x"), it.get("y"),
                                        str(it.get("label"))[:22], it.get("kind", "")))
    if mode != "tap":
        return
    want = sys.argv[2]
    hit = None
    # 精确优先，避免"微信号：xxx"被当成"微信"标签（实测踩过）
    for it in items:
        if str(it.get("label", "")).strip() == want:
            hit = it
            break
    if not hit:
        for it in items:
            if str(it.get("label", "")).strip().startswith(want):
                hit = it
                break
    if not hit:
        for it in items:
            if want in str(it.get("label", "")):
                hit = it
                break
    if not hit:
        print("没找到目标元素:", want)
        return
    x, y = int(hit["x"]), int(hit["y"])
    print("点击 (%d,%d) ← %s" % (x, y, hit.get("label")))
    portal("/tap", {"x": x, "y": y})
    time.sleep(2.5)
    after = shot("after")
    print("点后截图:", after)
    print("点后模型看到：", vlm(after, "一句话说明当前页面是什么页面（看顶部标题和底部标签）。")[:200])


if __name__ == "__main__":
    main()