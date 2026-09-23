#!/usr/bin/env python3
"""portal_probe.py — 探测 mobilerun portal HTTP API 的真实数据结构（on-device 侧）"""
import json
import os
import urllib.request

BASE = "http://127.0.0.1:8080"
TOKEN = os.environ.get("PORTAL_TOKEN", "")  # 本机 portal 的 Bearer token
OUT = os.path.expanduser("~/bridge/out")


def req(path, method="GET", payload=None, timeout=20):
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + TOKEN)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read()


def unwrap(raw):
    d = json.loads(raw)
    if isinstance(d, dict):
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


def walk(node, depth, count):
    if count[0] > 14 or depth > 4:
        return
    if isinstance(node, dict):
        props = {
            k: node.get(k)
            for k in ("text", "contentDescription", "className", "clickable",
                      "boundsInScreen", "bounds", "resourceId", "isEditable")
            if node.get(k) not in (None, "", False)
        }
        if props:
            print("  " * depth + json.dumps(props, ensure_ascii=False)[:220])
            count[0] += 1
        for c in node.get("children", []) or []:
            walk(c, depth + 1, count)


def main():
    os.makedirs(OUT, exist_ok=True)

    print("== version ==")
    print(req("/version")[:300])

    print("== state_full ==")
    raw = req("/state_full")
    print("raw bytes:", len(raw))
    with open(os.path.join(OUT, "state_full_raw.json"), "wb") as f:
        f.write(raw)
    data = unwrap(raw)
    with open(os.path.join(OUT, "state_full.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    if isinstance(data, dict):
        print("top keys:", list(data.keys()))
        t = data.get("a11y_tree")
        if isinstance(t, dict):
            print("a11y_tree dict keys:", list(t.keys())[:20])
            walk(t, 0, [0])
        elif isinstance(t, list):
            print("a11y_tree list len:", len(t))
            for n in t[:3]:
                walk(n, 0, [0])
        ph = data.get("phone_state")
        print("phone_state:", json.dumps(ph, ensure_ascii=False)[:400] if ph else None)
    else:
        print("state type:", type(data))

    print("== screenshot ==")
    shot = req("/screenshot")
    print("shot bytes:", len(shot), "magic:", shot[:8])
    with open(os.path.join(OUT, "screen.png"), "wb") as f:
        f.write(shot)

    print("== probe done ==")


if __name__ == "__main__":
    main()
