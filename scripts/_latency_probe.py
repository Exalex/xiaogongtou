"""延迟实测探针：Jev（云）vs qwen（局域网文本）vs portal（截图/状态）。
2026-09-29 · 为"执行架构设计"的时间预算提供实测依据。只读操作，不改手机状态。
"""
import json, time, urllib.request

SEC = json.load(open("D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/logs/secrets.json", encoding="utf-8"))
JEV_KEY = SEC["jev_key"]
JEV_URL = "https://api.typesafe.ai/v1/systemone"


def post(url, payload, headers, timeout=90, proxy=None):
    op = urllib.request.build_opener(urllib.request.ProxyHandler(proxy or {}))
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    t0 = time.time()
    with op.open(req, timeout=timeout) as r:
        b = r.read()
    return time.time() - t0, b


elems = ["hao —— 每日任务", "张江店客服2号15002148216", "星聚桌游俱乐部", "公众号",
         "【京东外卖】官方福利群E671", "微信", "通讯录", "发现", "我", "服务通知",
         "订阅号消息", "文件传输助手"]
criteria = {("elem_%d" % i): ("元素%d：%s" % (i, t)) for i, t in enumerate(elems)}
criteria.update({"scroll_down": "目标不在屏幕内，向下滑动", "back": "返回上一页", "done": "任务已完成"})
state = {"task": "给 hao 发一条消息：test", "recent_steps": ["step1: 打开微信（com.tencent.mm）"],
         "screen_elements": [{"id": "elem_%d" % i, "text": t} for i, t in enumerate(elems)]}
questions = {"target": {"type": "choice",
                        "instructions": "为完成 `task`，下一步应选哪个动作？答案必须从 `screen_elements` 或 滑动/返回/完成 中选择。",
                        "criteria": criteria}}
payload = {"model": "jev-latest", "state": state, "questions": questions}

for i in range(2):
    try:
        dt, b = post(JEV_URL, payload, {"Authorization": "Bearer " + JEV_KEY})
        ans = json.loads(b).get("answers", {})
        print("JEV #%d direct: %.2fs  answers=%s" % (i + 1, dt, json.dumps(ans, ensure_ascii=False)[:180]))
    except Exception as e:
        print("JEV #%d direct ERR: %r" % (i + 1, e)[:200])
        try:
            dt, b = post(JEV_URL, payload, {"Authorization": "Bearer " + JEV_KEY},
                         proxy={"https": "http://127.0.0.1:7897", "http": "http://127.0.0.1:7897"})
            ans = json.loads(b).get("answers", {})
            print("JEV #%d proxy: %.2fs  answers=%s" % (i + 1, dt, json.dumps(ans, ensure_ascii=False)[:180]))
        except Exception as e2:
            print("JEV #%d proxy ERR: %r" % (i + 1, e2)[:200])

for i in range(2):
    try:
        p2 = {"model": "qwen3.8-flash-next",
              "messages": [{"role": "user", "content": "一句话回答：1+1 等于几？"}],
              "max_tokens": 50, "chat_template_kwargs": {"enable_thinking": False}}
        dt, b = post("http://192.168.3.75:8888/v1/chat/completions", p2, {"Authorization": "Bearer 123"})
        txt = json.loads(b)["choices"][0]["message"].get("content", "")
        print("QWEN text #%d: %.2fs  -> %s" % (i + 1, dt, txt[:60]))
    except Exception as e:
        print("QWEN #%d ERR: %r" % (i + 1, e)[:160])
