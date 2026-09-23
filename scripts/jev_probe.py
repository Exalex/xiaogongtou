#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jev_probe.py — 实测 TypeSafe Jev (System One) 的速度与「元素选择」能力（PC 侧）"""
import json
import os
import time
import urllib.request

KEY = os.environ.get("JEV_KEY", "")  # 本机运行时设置环境变量（或见 ~/bridge/secrets.json）
URL = "https://api.typesafe.ai/v1/systemone"


def ask(state, questions, timeout=40):
    payload = {"model": "jev-latest", "state": state, "questions": questions}
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + KEY)
    req.add_header("Content-Type", "application/json")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
        return {"ok": True, "dt": time.time() - t0, "resp": d}
    except Exception as e:
        return {"ok": False, "dt": time.time() - t0, "err": repr(e)}


def main():
    print("== T1: connectivity + basic noul ==")
    r = ask({"screen_text": "设置首页：WLAN、蓝牙、电池、显示与亮度、关于手机"},
            {"has_battery": {"type": "noul", "instructions": "材料中是否出现与'电池'相关的条目？"}})
    print("dt=%.2fs" % r["dt"], "->", json.dumps(r.get("resp", r.get("err")), ensure_ascii=False)[:300])

    print("== T2: element pick (agent scenario) ==")
    elems = [{"idx": i, "text": t} for i, t in enumerate([
        "设置", "WLAN", "蓝牙", "连接与共享", "流量使用情况", "电池", "存储",
        "显示与亮度", "声音与振动", "密码与安全", "位置信息", "应用管理", "关于手机"])]
    criteria = {f"elem_{e['idx']}": f"点击元素{e['idx']}：{e['text']}" for e in elems}
    criteria.update({"scroll_down": "目标不在屏幕上，向下滑动",
                     "scroll_up": "向上滑动", "back": "返回上一页", "done": "任务已完成"})
    state = {"task": "查看电池电量百分比", "screen": {"app": "设置", "elements": elems}}
    r = ask(state, {"target": {"type": "choice",
        "instructions": "为完成 `task`，下一步应选哪个动作？请从 `screen.elements` 中找。",
        "criteria": criteria}})
    print("dt=%.2fs" % r["dt"], "->", json.dumps(r.get("resp", r.get("err")), ensure_ascii=False)[:400])

    print("== T3: speed x6 (same request) ==")
    ts = []
    for _ in range(6):
        r = ask(state, {"target": {"type": "choice",
            "instructions": "为完成 `task`，下一步应选哪个动作？", "criteria": criteria}})
        ts.append(round(r["dt"], 2))
    print("latencies:", ts)

    print("== T4: blocker scenario (popup) ==")
    els = [{"idx": 0, "text": "更新提示：新版本可用"}, {"idx": 1, "text": "立即更新"},
           {"idx": 2, "text": "稍后再说"}, {"idx": 3, "text": "微信"},
           {"idx": 4, "text": "通讯录"}, {"idx": 5, "text": "发现"}, {"idx": 6, "text": "我"}]
    crit2 = {f"elem_{e['idx']}": f"点击元素{e['idx']}：{e['text']}" for e in els}
    crit2.update({"scroll_down": "向下滑动", "back": "返回", "done": "已完成"})
    r = ask({"task": "打开微信的'发现'页", "screen": {"app": "微信", "elements": els}},
            {"target": {"type": "choice",
                        "instructions": "为完成 `task`，下一步应选哪个动作？（注意先处理遮挡弹窗）",
                        "criteria": crit2}})
    print("dt=%.2fs" % r["dt"], "->", json.dumps(r.get("resp", r.get("err")), ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
