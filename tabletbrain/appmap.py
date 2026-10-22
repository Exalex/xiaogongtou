#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""appmap.py —— App 探索地图：通用格式 + 读写 + 页面识别 + 任务提示

为什么要有这个东西（2026-10-22 用户提出，实测验证）：
  每条任务都在重新"认路"。同一个 App 昨天走过 3 遍，今天再来一遍还是要
  逐个试：搜索在哪？排行榜藏在哪？—— 每步 3~4 秒，试错十几次就是一分多钟。
  正确做法：空闲时把 App 逛一遍，记下"什么在哪、怎么走"，任务开工先查地图。

格式（xgt-appmap/1）：

  {
    "format": "xgt-appmap/1",
    "pkg": "tv.danmaku.bilibilihd",
    "label": "哔哩哔哩HD",
    "exploredAt": "2026-10-22T23:10:00",
    "durationSec": 420, "probes": 37,
    "home": "a1b2c3",
    "screens": {
      "a1b2c3": {"keys": ["直播","推荐","热门","追番","影视"],
                 "activity": "tv.danmaku.bili.MainActivityV2",
                 "path": [], "name": "首页"},
      "d4e5f6": {"keys": ["排行榜","每周必看","入站必刷"],
                 "activity": "...", "path": ["热门"], "name": "热门"}
    },
    "edges": [{"from":"a1b2c3","tap":"热门","to":"d4e5f6"}],
    "dead":  [{"from":"a1b2c3","tap":"直播"}],
    "entries": {"排行榜": {"path": ["热门","排行榜"], "screen": "g7h8i9"}}
  }

三条设计原则：
  1. **页面用"特征词"认，不用坐标/截图**——布局微调、分辨率变化都不失效
  2. **entries 是给任务用的主入口**：`要 X → 首页 → A → B`，一句话说清路线
  3. **票数可查**：每条边都有出处（哪一步试出来的），人工能核对、能改

依赖：纯标准库。设备端与 PC 端共用同一份。
"""
import hashlib
import json
import os
import re
import time

FORMAT = "xgt-appmap/1"
MAP_DIR_NAME = os.path.join("bridge", "skills", "app_maps")

# 页面识别阈值：地图节点的特征词有多少比例出现在当前屏幕上，才算"就是这一页"
PAGE_MATCH_MIN = 0.6
# 每页最多记多少个特征词（少了不稳，多了容易撞车）
MAX_KEYS = 8


def map_dir(base=None):
    root = base or os.path.expanduser("~")
    return os.path.join(root, MAP_DIR_NAME)


def map_path(pkg, base=None):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", pkg or "unknown")
    return os.path.join(map_dir(base), safe + ".json")


# ---------------------------------------------------------------- 页面指纹

def screen_hash(elems):
    """整屏哈希：只用来判"点了一下之后屏幕变了没"，要求严格。
    动态内容（视频标题、推荐位）会让哈希每次都变 → 所以只用于瞬时对比，
    不作为地图里的页面身份。"""
    labels = sorted(str(e[3] if isinstance(e, (list, tuple)) else e).strip()
                    for e in elems)
    raw = "|".join(l for l in labels if l)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _is_keyish(lab):
    """能不能当"页面特征词"：短、像导航/按钮，不像正文或数字。"""
    s = str(lab or "").strip()
    if not s or len(s) < 2 or len(s) > 12:
        return False
    if re.fullmatch(r"[\d\s.,:%+-]+", s):
        return False
    if re.search(r"\d{4,}", s):          # 播放量/时间戳这类
        return False
    return True


def nav_score(lab, y, h):
    """给"这个元素有多像导航入口"打分。

    为什么需要（实测）：B站首页的前 8 个短标签里有 3 个是 UP 主名字，
    每次刷新都变 → 页面特征词不可复现 → 下次任务认不出这一页。
    导航入口有稳定特征：常带「标签/按钮/入口」字样、位于顶部或底部导航带、字短。
    """
    s = str(lab or "")
    sc = 0.0
    if re.search(r"标签|按钮|入口|菜单|tab|导航", s):
        sc += 5.0
    if h:
        if y < h * 0.18:
            sc += 2.0
        elif y > h * 0.84:
            sc += 2.0
    core = re.split(r"[,，|/、]", s)[0].strip()
    if 2 <= len(core) <= 4:
        sc += 1.0
    elif len(core) <= 6:
        sc += 0.5
    return sc


def node_id(elems):
    """页面身份 = 特征词集合的哈希。

    为什么不用整屏哈希（实测踩坑）：B站推荐流每次刷新，标题/UP 主全变，
    整屏哈希跟着变 → 同一个"首页"每次都是新页面，探索器永远走不回去。
    特征词只取导航类文字（tab、按钮、入口），内容刷新不影响 → 同一页始终同一身份。
    """
    keys = sorted(page_keys(elems))
    if not keys:
        return "empty"
    return hashlib.md5("|".join(keys).encode("utf-8")).hexdigest()[:10]


def page_keys(elems, limit=MAX_KEYS):
    """从元素清单里挑"最像这一页身份"的特征词。

    按 nav_score 排序取前 limit 个（而不是按出现顺序），
    这样动态内容（UP 主名、推荐位标题）不会挤掉真正的导航词。
    """
    items = []
    h = 0
    for e in elems:
        y = e[2] if isinstance(e, (list, tuple)) and len(e) > 2 else 0
        if isinstance(y, int):
            h = max(h, y)
    for e in elems:
        lab = str(e[3] if isinstance(e, (list, tuple)) else e).strip()
        if not lab:
            continue
        y = e[2] if isinstance(e, (list, tuple)) and len(e) > 2 else 0
        head = re.split(r"[,，|/、]", lab)[0].strip()
        cand = head if _is_keyish(head) else (lab if _is_keyish(lab) else "")
        if not cand:
            continue
        items.append((nav_score(lab, y, h), cand))
    items.sort(key=lambda kv: -kv[0])
    seen, out = set(), []
    for _sc, cand in items:
        if cand in seen:
            continue
        seen.add(cand)
        out.append(cand)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 读写

def load_map(pkg, base=None):
    """读某 App 的地图；没有/损坏一律返回 None（调用方按"无地图"处理）。"""
    try:
        p = map_path(pkg, base)
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            return None
        return d
    except Exception:
        return None


def save_map(m, base=None):
    p = map_path(m.get("pkg") or "unknown", base)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def list_maps(base=None):
    """已有哪些 App 的地图 → {pkg: 概要}。"""
    out = {}
    d = map_dir(base)
    try:
        names = os.listdir(d)
    except Exception:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                m = json.load(f)
            if m.get("format") == FORMAT:
                out[m.get("pkg") or n[:-5]] = {
                    "label": m.get("label") or "",
                    "screens": len(m.get("screens") or {}),
                    "entries": len(m.get("entries") or {}),
                    "exploredAt": m.get("exploredAt") or "",
                }
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- 图计算

def build_entries(home, edges):
    """从边表算"每个可点入口"从首页出发的最短路径。

    产出物就是任务真正要用的东西：
      {"排行榜": {"path": ["热门","排行榜"], "screen": "..."}}
    读作：想看到排行榜，先点热门，再点排行榜。
    """
    adj = {}
    for e in edges or []:
        f, t = e.get("from"), e.get("to")
        if not f or not t:
            continue
        adj.setdefault(f, []).append((e.get("tap") or "", t))

    # BFS：首页 → 各页的最短标签序列
    path_to = {home: []}
    queue = [home]
    while queue:
        cur = queue.pop(0)
        for tap, nxt in adj.get(cur, []):
            if nxt in path_to and len(path_to[nxt]) <= len(path_to[cur]) + 1:
                continue
            path_to[nxt] = path_to[cur] + [tap]
            queue.append(nxt)

    entries = {}
    for cur, lst in adj.items():
        base = path_to.get(cur)
        if base is None:
            continue
        for tap, nxt in lst:
            if not tap:
                continue
            # 同一标签多处出现时，保留路径最短的那条
            cand = base + [tap]
            old = entries.get(tap)
            if old is None or len(cand) < len(old.get("path") or []):
                entries[tap] = {"path": cand, "screen": nxt}
    return entries


def distinct_keys(keys, parent_keys):
    """这一页**独有**的特征词（去掉从父页带过来的）。

    为什么需要（实测踩坑）：B站每个页面顶部都有同一排 tab（直播/推荐/热门/追番/影视），
    只看"本页全部导航词"根本分不清自己在哪个 tab。
    真正能区分的是"这一页多出来的词" —— 热门页多出「排行榜/每周必看/入站必刷」，
    这几个词才是这一页的身份证，也正好是任务里要说的"入口"。
    """
    p = set(parent_keys or [])
    return [k for k in (keys or []) if k not in p]


def path_node_id(parent_id, tap):
    """探索期的页面身份 = 父页 + 点进来的那个标签。

    比内容哈希稳：B站推荐流每次刷新内容都变，内容哈希认不住同一个页面；
    而"从首页点热门到的那个地方"永远是同一个地方。
    """
    raw = "%s|%s" % (parent_id or "root", str(tap or ""))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def identify_page(m, elems):
    """当前屏幕最像地图里的哪一页 → (screen_id, 命中率, screens)。

    优先用**独有特征词**（distinct）判断，独有词不足时才退回全部特征词。
    这样"同一个 tab 栏下的不同页面"也能区分开。
    """
    if not m:
        return None, 0.0, {}
    screens = m.get("screens") or {}
    if not screens:
        return None, 0.0, {}
    cur = set()
    for e in elems:
        lab = str(e[3] if isinstance(e, (list, tuple)) else e).strip()
        if lab:
            cur.add(lab)
            cur.add(re.split(r"[,，|/、]", lab)[0].strip())
    best, best_r = None, 0.0
    for sid, node in screens.items():
        keys = node.get("distinct") or []
        pool = keys if len(keys) >= 2 else (node.get("keys") or [])
        if len(pool) < 2:
            continue
        hit = sum(1 for k in pool if k in cur)
        r = hit / float(len(pool))
        # 独有词命中权重更高（+0.1），避免"全特征词"页面抢走独有页的结果
        w = r + (0.1 if (keys and len(keys) >= 2) else 0.0)
        if r >= PAGE_MATCH_MIN and w > best_r:
            best, best_r = sid, w
    return best, min(best_r, 1.0), screens


# ---------------------------------------------------------------- 给任务用的提示

_STOP = set("的 了 和 与 及 或 在 把 给 我 你 他 它 是 有 没有 一个 一下 这个 那个 什么 "
            "帮 帮忙 打开 查看 看看 告诉 请 一下".split())


def _words(text):
    """任务文本 → 有意义的词（中文按 2 字滑窗 + 英文/数字整词）。"""
    t = str(text or "")
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}", t):
        out.add(w.lower())
    zh = re.sub(r"[^\u4e00-\u9fff]", " ", t)
    for seg in zh.split():
        for n in (2, 3, 4):
            for i in range(0, max(0, len(seg) - n + 1)):
                out.add(seg[i:i + n])
    return {w for w in out if w and w not in _STOP}


def match_entries(m, task, limit=4):
    """任务文本 ↔ 地图入口名：找出这次任务大概要找的入口。"""
    if not m:
        return []
    entries = m.get("entries") or {}
    if not entries:
        return []
    tw = _words(task)
    tl = str(task or "")
    scored = []
    for name, spec in entries.items():
        nm = str(name or "").strip()
        if not nm:
            continue
        s = 0.0
        if nm in tl:
            s += 3.0                      # 原样出现，最可信
        if any(w == nm.lower() for w in tw):
            s += 2.0
        if any(w in nm for w in tw if len(w) >= 2):
            s += 1.0
        if s > 0:
            scored.append((s, len(nm), nm, spec))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(nm, spec) for _s, _n, nm, spec in scored[:limit]]


def is_enabled(base=None):
    """地图注入默认**关闭**，需要显式打开。

    2026-10-22 A/B 实测（酷安搜索微信）：
      A 无地图      10 步 / 65.5s
      B 长地图提示   9 步 / 84.0s   ← 省 1 步但慢 18s（提示太长把模型拖慢）
      B2 精简提示    9 步 / 71.7s   ← 仍慢 6s
    结论：在这个"已有锚点"的场景下，地图省的那一步落入噪声，而额外提示词的代价是实的。
    所以默认关闭，等两件事做到再打开：
      ① 入口质量上去（现在还有"图片1/用户头像"这类噪声）
      ② 只有在**确实没别的线索**时才注入（锚点/手写路径都没有的 App）
    开关：环境变量 XGT_APPMAP=1，或 ~/bridge/skills/.appmap_on 文件存在。
    """
    if os.environ.get("XGT_APPMAP", "") in ("1", "true", "yes", "on"):
        return True
    try:
        root = base or os.path.expanduser("~")
        return os.path.exists(os.path.join(root, "bridge", "skills", ".appmap_on"))
    except Exception:
        return False


def hint_for(pkg, task, elems, base=None):
    """给 agent 的地图提示 —— **越短越好**，且默认关闭（见 is_enabled）。

    第一版把整张地图塞进提示词（当前页 + 全部入口 + 说明），
    结果单步模型耗时从 1.6~4 秒涨到 4.7~6.3 秒，省 1 步却慢 18 秒，净负。
    改为只输出两样东西，各一行：要找的入口怎么走；如果不在首页，说清在哪。
    """
    if not is_enabled(base):
        return ""
    m = load_map(pkg, base)
    if not m:
        return ""

    lines = []

    # ① 这次任务要的入口：只取最匹配的 1 条，一行说完
    hits = match_entries(m, task, limit=1)
    if hits:
        nm, spec = hits[0]
        pth = spec.get("path") or []
        if pth:
            lines.append("【地图】要「%s」：%s" % (nm, " → ".join(pth)))

    # ② 当前在哪：只有"不在首页"才说，且只占一行
    if not lines:
        sid, ratio, screens = identify_page(m, elems)
        if sid and sid != m.get("home"):
            node = screens.get(sid) or {}
            pth = node.get("path") or []
            if pth:
                lines.append("【地图】你在「%s」页（从首页：%s）"
                             % (node.get("name") or pth[-1], " → ".join(pth)))

    if not lines:
        return ""
    return "\n\n" + "\n".join(lines)


def stats(m):
    """人看的摘要。"""
    if not m:
        return "无地图"
    return "%s：%d 页 / %d 条边 / %d 个入口（探索于 %s，耗时 %ss）" % (
        m.get("label") or m.get("pkg"), len(m.get("screens") or {}),
        len(m.get("edges") or []), len(m.get("entries") or {}),
        m.get("exploredAt") or "?", m.get("durationSec") or 0)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for pkg, s in sorted(list_maps().items()):
            print("%-40s %s" % (pkg, s))
    elif len(sys.argv) > 1:
        mm = load_map(sys.argv[1])
        print(stats(mm))
        if mm:
            print(json.dumps(mm.get("entries") or {}, ensure_ascii=False, indent=1))
