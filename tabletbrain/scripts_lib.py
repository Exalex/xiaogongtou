#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts_lib.py — 确定性骨架（纯逻辑，可离线单测）

承载《本机自动化可靠性加强方案》里除"像素采集"外的全部判定逻辑：
  任务家族 / 页面身份 / 起点归位 / 经验坐标注入 / 脚本库匹配与重放 / 成功即固化 /
  子目标 / 硬闸门 / 失败归类 / 开工可行性 / 分级预算

设计约束：
  · 只 import json / os / re / time（外加同目录的 anchors.py，缺失时自动退化）
  · 不直接调 portal / bridge / subprocess —— 所有 IO 由调用方经参数或 ctx 注入
  · 因此本模块可在 PC 上离线单测（见 _test_scripts_lib.py）
"""
import json
import os
import re
import time

try:
    import anchors as _AN
except Exception:                                    # anchors.py 缺失 → 退化为"只看文本锚点"
    _AN = None

SKILLS_DIR = os.path.expanduser("~/bridge/skills")

# 安全护栏词（与 mini_agent 保持一致；此处独立定义避免循环依赖）
LOGIN_WORDS = ("登录", "验证码", "密码", "注册账号", "一键登录")
DANGER_WORDS = ("验证码", "密码")

# 弹窗类一次性步骤的关键词（固化脚本时用于清洗）
POPUP_WORDS = ("跳过", "我知道了", "知道了", "允许", "以后再说", "暂不", "关闭广告", "立即更新")


# ================================================================ JSON 读取（带 mtime 缓存）
_CACHE = {}


def _load_json(path, default):
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return default
    key = (path, mt)
    if key in _CACHE:
        return _CACHE[key]
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = default
    for k in list(_CACHE):
        if k[0] == path and k != key:
            _CACHE.pop(k, None)
    _CACHE[key] = d
    return d


def _skills_dir(d=None):
    return d or SKILLS_DIR


# ================================================================ 锚点判定（委托 anchors，缺失则退化）
def anchor_level(anchors, elems=None, act="", fp=None):
    if not anchors:
        return ""
    if isinstance(anchors, (list, tuple)):
        anchors = {"text": list(anchors)}
    if not isinstance(anchors, dict):
        return ""
    if _AN is not None:
        return _AN.anchor_level(anchors, elems, act, fp)
    # 退化：只认文本锚点
    texts = [str(t) for t in (anchors.get("text") or anchors.get("verify") or []) if t]
    if texts and elems:
        labels = "|".join(str(e[3]) for e in elems)
        hits = sum(1 for t in texts if t in labels)
        if hits >= min(2, len(texts)):
            return "L3"
    return ""


def verify_anchors(anchors, elems=None, act="", fp=None):
    return anchor_level(anchors, elems, act, fp) != ""


# ================================================================ App 卡片（结构升级 + 双向兼容）
def _norm_spot(s):
    """旧格式 [label,x,y,[whens]] / 新格式 {label,x,y,whens,page,hits,miss,last_ok} → dict"""
    try:
        if isinstance(s, (list, tuple)):
            return {"label": str(s[0]), "x": int(s[1]), "y": int(s[2]),
                    "whens": [str(w) for w in (s[3] if len(s) > 3 else [])],
                    "page": "", "hits": 0, "miss": 0, "last_ok": 0}
        if isinstance(s, dict):
            return {"label": str(s.get("label") or ""),
                    "x": int(s.get("x") or 0), "y": int(s.get("y") or 0),
                    "whens": [str(w) for w in (s.get("whens") or [])],
                    "page": str(s.get("page") or ""),
                    "hits": int(s.get("hits") or 0), "miss": int(s.get("miss") or 0),
                    "last_ok": int(s.get("last_ok") or 0)}
    except Exception:
        pass
    return None


def _norm_page(p):
    if not isinstance(p, dict):
        return None
    ver = p.get("verify")
    if isinstance(ver, list):
        ver = {"text": [str(x) for x in ver]}
    elif not isinstance(ver, dict):
        ver = {}
    return {"name": str(p.get("name") or ""),
            "activity": str(p.get("activity") or ""),
            "fingerprint": p.get("fingerprint"),
            "dead_end": bool(p.get("dead_end")),     # 死胡同页（如搜索页残留）→ 必须归位
            "verify": ver}


def normalize_card(v):
    """统一 App 卡片格式（向后兼容旧数据）→
    {"hint": str, "version": int, "home_path": dict|None,
     "pages": [{name,activity,fingerprint,verify}],
     "spots": [{label,x,y,whens,page,hits,miss,last_ok}]}"""
    out = {"hint": "", "version": 1, "home_path": None, "pages": [], "spots": []}
    if isinstance(v, str):
        out["hint"] = v
        return out
    if not isinstance(v, dict):
        return out
    out["hint"] = str(v.get("hint") or "")
    try:
        out["version"] = int(v.get("version") or 1)
    except Exception:
        pass
    hp = v.get("home_path")
    if isinstance(hp, dict):
        out["home_path"] = hp
    for p in (v.get("pages") or []):
        np = _norm_page(p)
        if np and np["name"]:
            out["pages"].append(np)
    for s in (v.get("spots") or []):
        ns = _norm_spot(s)
        if ns and ns["label"]:
            out["spots"].append(ns)
    return out


def cards_of(cards=None, d=None):
    """卡片的"当前快照"：内置由调用方注入；此处只负责读外部 apps.json 并合并。"""
    base = {}
    if isinstance(cards, dict):
        for k, v in cards.items():
            base[str(k)] = normalize_card(v)
    ext = _load_json(os.path.join(_skills_dir(d), "apps.json"), {})
    if isinstance(ext, dict):
        for k, v in ext.items():
            k = str(k)
            old = base.get(k)
            if isinstance(v, dict):
                nv = normalize_card(v)
                if not old:
                    base[k] = nv
                    continue
                # 深合并：外部**给了的字段**才覆盖，未给的保留内置（避免重复维护 hint）
                merged = dict(old)
                if nv.get("hint"):
                    merged["hint"] = nv["hint"]
                if nv.get("home_path"):
                    merged["home_path"] = nv["home_path"]
                if nv.get("pages"):
                    merged["pages"] = nv["pages"]
                if nv.get("spots"):
                    merged["spots"] = nv["spots"]
                merged["version"] = max(int(merged.get("version") or 1), int(nv.get("version") or 1))
                base[k] = merged
            else:                                    # 外部给 str → 只覆盖 hint，保留已有 pages/spots
                if old:
                    old = dict(old)
                    old["hint"] = str(v)
                    base[k] = old
                else:
                    base[k] = normalize_card(str(v))
    return base


# ================================================================ 页面身份 / 起点归位
def page_id(pkg, elems=None, act="", fp=None, cards=None):
    """当前页面身份（""=未知页）。按 L1→L2→L3 取信度最高者。"""
    card = (cards or {}).get(pkg or "") or {}
    best, best_rank = "", 99
    rank_of = {"L1": 1, "L2": 2, "L3": 3}
    for pg in (card.get("pages") or []):
        lvl = anchor_level(pg, elems, act, fp)
        r = rank_of.get(lvl, 99)
        if r < best_rank:
            best, best_rank = str(pg.get("name") or ""), r
    return best


def page_anchors(pkg, page_name, cards=None):
    """取某页的锚点定义（供调试/校验）"""
    card = (cards or {}).get(pkg or "") or {}
    for pg in (card.get("pages") or []):
        if str(pg.get("name") or "") == str(page_name or ""):
            return pg
    return None


def need_home(pkg, elems=None, act="", fp=None, cards=None, target=None):
    """是否需要先归位。
    触发条件（卡片有 home_path 且登记了 pages）：
      · 给了 target（期望的起始页名）→ 当前页不在 target 里 → 归位
      · 否则 → 当前页"未知"或命中标记了 dead_end 的页 → 归位
    保守策略：没登记 pages 的卡片一律不归位（无法判定，避免误伤）。"""
    card = (cards or {}).get(pkg or "") or {}
    if not card.get("home_path"):
        return False
    pages = card.get("pages") or []
    if not pages:
        return False
    cur = page_id(pkg, elems, act, fp, cards)
    if target:
        tset = set(target) if isinstance(target, (list, tuple, set)) else {target}
        return cur not in tset
    if not cur:
        return True
    for pg in pages:
        if str(pg.get("name") or "") == cur:
            return bool(pg.get("dead_end"))
    return False


def home_steps(card):
    """卡片 home_path → 返航动作序列。

    顺序很关键：**先点"入口 tab"，再按返回键**。
    原因（2026-10-11 实证）：App 已在根页时按返回键会**直接退出 App**（随后回到桌面，
    归位彻底失败）；而点入口 tab 在任何标签页都是安全的（已在入口页时是空操作）。
    调用方必须"每步后验收、达标即停"，否则多余的 BACK 仍会把 App 退掉。"""
    hp = (card or {}).get("home_path") or {}
    out = []
    tab = hp.get("tap_home_tab")
    if isinstance(tab, (list, tuple)) and len(tab) >= 2:
        try:
            out.append({"action": "tap", "x": int(tab[0]), "y": int(tab[1]), "pick": "入口tab"})
        except Exception:
            pass
    # 无入口 tab 时，允许**有界 BACK**（治"App 恢复上次的子页"）：
    #   2026-10-11 血泪：无界 BACK 会把 App 退到桌面（头条/抖音实测）。故：
    #     · 上限 min(back, max_back, 3)
    #     · 调用方**每步验收、达标即停**；一旦发现离开 App 立即中止并**补开该 App**
    #   （2026-10-12 回归实证：设置卡片只配了 back、没有 tab → 之前不做归位 →
    #     设置恢复上次子页时 WiFi 脚本第 2 步读不到内容而断。）
    if not out:
        try:
            n = min(int(hp.get("back") or 0), int(hp.get("max_back") or 3), 3)
        except Exception:
            n = 0
        for _ in range(max(0, n)):
            out.append({"action": "key", "key_code": 4})
    return out


def home_until(card):
    """返航验收锚点（列表 of 特征词）。"""
    hp = (card or {}).get("home_path") or {}
    return [str(w) for w in (hp.get("until") or []) if w]


def _page_words(pg):
    ver = (pg or {}).get("verify")
    if isinstance(ver, dict):
        return [str(t) for t in (ver.get("text") or []) if t]
    if isinstance(ver, (list, tuple)):
        return [str(t) for t in ver if t]
    return []


def entry_pages(card):
    """卡片声明的"入口页"名列表：home_path.until 特征词命中的页；没有则取 pages[0]。
    用途：脚本重放时传 target —— 只要不在入口页就先归位（治"App 恢复上次页面"）。"""
    pages = (card or {}).get("pages") or []
    if not pages:
        return []
    until = home_until(card)
    names = []
    if until:
        for pg in pages:
            if any(w in _page_words(pg) for w in until):
                n = str(pg.get("name") or "")
                if n and n not in names:
                    names.append(n)
    if names:
        return names
    n0 = str(pages[0].get("name") or "")
    return [n0] if n0 else []


# ================================================================ 经验坐标注入（页面过滤 + 自校验 + 失效）
def spot_key(pkg, label):
    return "%s|%s" % (pkg or "", label or "")


def app_coords2(pkg, elems, cur_page="", dead=None, cards=None):
    """返回可注入的虚拟元素坐标 [{"label","x","y","pkg"}]。
    ① 页面过滤：spot.page 非空且 ≠ 当前页 → 跳过
    ② 特征词过滤：whens 非空且无一命中 → 跳过
    ③ 自校验 A：80px 内已有同名真实元素 → 不注入（模型直接点真实元素即可）
    ④ 自校验 B：坐标被别的元素占据 且 该坐标历史 miss > hits → 判失效，不注入
    ⑤ 失效名单 dead（本次运行内已点过没反应的坐标）→ 跳过
    """
    cards = cards or {}
    dead = dead or set()
    elems = elems or []
    if pkg:
        cand = [(pkg, cards.get(pkg) or {})]
    else:
        cand = list(cards.items())
    labels = "|".join(str(e[3]) for e in elems)
    out = []
    for _p, card in cand:
        for sp in (card.get("spots") or []):
            lbl = str(sp.get("label") or "")
            if not lbl:
                continue
            if spot_key(_p, lbl) in dead:
                continue
            pg = str(sp.get("page") or "")
            if pg and cur_page and pg != cur_page:
                continue
            whens = sp.get("whens") or []
            if whens and not any(w and w in labels for w in whens):
                continue
            x, y = int(sp.get("x") or 0), int(sp.get("y") or 0)
            same_near = [e for e in elems
                         if abs(e[1] - x) < 80 and abs(e[2] - y) < 80 and lbl[:4] in str(e[3])]
            if same_near:
                continue                             # 真实元素已在屏上 → 无需虚拟注入
            occ = [e for e in elems if abs(e[1] - x) < 40 and abs(e[2] - y) < 40]
            if occ and int(sp.get("miss") or 0) > int(sp.get("hits") or 0):
                continue                             # 坐标被占且历史命中率差 → 失效
            out.append({"label": lbl, "x": x, "y": y, "pkg": _p})
    return out


# ================================================================ 任务家族
FAMILIES_BUILTIN = {
    "read":    {"name": "读数", "budget": 26, "skeleton": ["open_app", "goto", "read"],
                "desc": "打开应用 → 到达目标页 → 读取指定元素"},
    "list":    {"name": "列表", "budget": 30, "skeleton": ["open_app", "goto", "collect", "answer"],
                "desc": "打开应用 → 到达目标页 → 滚动收集 → 输出前N"},
    "search":  {"name": "搜索", "budget": 25, "skeleton": ["open_app", "tap_search", "input", "submit", "read"],
                "desc": "打开应用 → 点搜索框 → 输入关键词 → 提交 → 读结果"},
    "send":    {"name": "发送", "budget": 40, "skeleton": ["open_app", "locate", "verify_identity", "input", "send", "verify_delivery"],
                "desc": "打开应用 → 定位对象 → 校验身份 → 输入 → 发送 → 校验送达"},
    "publish": {"name": "发布", "budget": 40, "skeleton": ["open_app", "pick_media", "edit", "caption", "stop_before_send"],
                "desc": "打开应用 → 选素材 → 编辑 → 填文案 → 停在发送前"},
}

# 家族判定的关键词（顺序敏感：先副作用，再搜索，再列表，最后读数）
FAMILY_KEYWORDS = (
    ("send",    ("发给", "发条", "发个", "发消息", "发一条", "告诉他", "跟他说", "给")),
    ("publish", ("发布", "发作品", "上传", "发抖音", "发个视频", "投稿")),
    ("search",  ("搜索", "搜一下", "搜一搜", "查一下", "查找", "搜关键词")),
    ("list",    ("前几", "前五", "前三", "前", "排行", "榜单", "热搜", "列表", "哪些", "几条", "都有", "全部")),
    ("read",    ("多少", "几点", "是什么", "看一下", "读一下", "查看", "看下", "看看",
                 "百分比", "百分之", "几度", "几格", "电量")),
)


def load_families(d=None):
    fams = {k: dict(v) for k, v in FAMILIES_BUILTIN.items()}
    ext = _load_json(os.path.join(_skills_dir(d), "families.json"), {})
    if isinstance(ext, dict):
        for k, v in ext.items():
            if isinstance(v, dict):
                cur = fams.get(str(k)) or {}
                cur = dict(cur)
                cur.update(v)
                fams[str(k)] = cur
    return fams


def match_family(plan, task="", families=None):
    """任务家族：优先用 plan.family（校验是已知家族）；否则关键词启发式。返回 ""=未知。"""
    fams = families or load_families()
    f = str((plan or {}).get("family") or "").strip().lower()
    if f in fams:
        return f
    t = re.sub(r"\s+", "", task or "")
    for key, kws in FAMILY_KEYWORDS:
        if key not in fams:
            continue
        for kw in kws:
            if kw and kw in t:
                return key
    return ""


def budget_of(family, families=None):
    fams = families or load_families()
    try:
        return int((fams.get(family) or {}).get("budget") or 25)
    except Exception:
        return 25


# ================================================================ 脚本库
def scripts_dir(d=None):
    return os.path.join(_skills_dir(d), "scripts")


def load_scripts(d=None):
    out = []
    p = scripts_dir(d)
    try:
        names = sorted(os.listdir(p))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        sc = _load_json(os.path.join(p, n), None)
        if isinstance(sc, dict) and sc.get("steps"):
            sc.setdefault("id", n[:-5])
            out.append(sc)
    return out


def _installed(pkg, apps):
    if not pkg or not apps:
        return True
    return any(str(a.get("packageName") or a.get("package") or "") == pkg for a in apps)


def has_answer_step(sc):
    """脚本是否含"产出答案"的步骤（extract_rank / extract_text / done）。
    没有这类步骤的脚本跑完也没有答案 → 绝不能当"完成"（2026-10-12 血泪：一个只有
    `open_app` 一步的自动固化脚本被判"完成"，输出"已按既定路径完成「…」"= 假成功）。"""
    for st in (sc.get("steps") or []):
        if not isinstance(st, dict):
            continue
        if str(st.get("do") or "") in ("extract_rank", "extract_text") or st.get("done"):
            return True
    return False


def match_script(task, family="", cur_pkg="", apps=None, scripts=None, d=None):
    """命中脚本（判定从紧）：
      ① status ∈ {active, candidate}；**candidate 必须已成功过 ≥1 次（ok≥1）才参与**
         （2026-10-12 准确率优先：不能拿"从未验证过的路径"去跑真任务）
      ② **match 关键词非空且命中**（空 match 会命中一切任务 → 2026-10-12 实证劫持事故）
      ③ **含产出答案的步骤**（否则会"假完成"）
      ④ family 一致（若都给出）⑤ app 已安装
    优先级：active > candidate；同级取 runs 多者。deprecated / draft 不参与。"""
    scripts = scripts if scripts is not None else load_scripts(d)
    t = re.sub(r"\s+", "", task or "").lower()
    best, best_key = None, None
    for sc in scripts:
        st = str(sc.get("status") or "active")
        if st not in ("active", "candidate"):
            continue
        if st == "candidate" and int(sc.get("ok") or 0) < 1:
            continue                      # 未验证过的候选路径 → 不自动重放
        # **排除词**：任务里出现排除词 → 不匹配。
        #   2026-10-12 血泪：脚本「开盘啦涨停家数」match=["开盘","涨停"]（OR 语义），
        #   任务「看今天**跌停**家数」含"开盘" → 命中 → **答了涨停数还判成功**（静默错答！）。
        nm = [re.sub(r"\s+", "", str(k)).lower() for k in (sc.get("not_match") or []) if k]
        if nm and any(k in t for k in nm):
            continue
        kws = [re.sub(r"\s+", "", str(k)).lower() for k in (sc.get("match") or []) if k]
        if not kws:                       # 空 match → 会命中一切任务，拒绝参与
            continue
        if not any(k in t for k in kws):
            continue
        if not has_answer_step(sc):       # 没有答案产出步骤 → 拒绝参与
            continue
        fam = str(sc.get("family") or "")
        if family and fam and fam != family:
            continue
        if not _installed(str(sc.get("app") or ""), apps):
            continue
        key = (0 if st == "active" else 1, -int(sc.get("runs") or 0))
        if best_key is None or key < best_key:
            best, best_key = sc, key
    return best


def replay(script, ctx):
    """按步重放脚本。每步执行后用三级锚点验收。
    返回 (ok, result, log, broken_at)；ok=False 时 broken_at = 断在第几步（1-based，0=脚本本身无效）。
    ctx（全部可选，缺失即降级）：
      get_elems() -> elems        get_activity() -> "pkg/Act"
      get_fp() -> bytes|None      do_action(act) -> (ok, err)
      tap_spot(name, step) -> (ok, err)         extract_rank(n) -> str
      read_text(t) -> str         log(s)
    """
    log = []

    def L(s):
        log.append(s)
        if ctx.get("log"):
            try:
                ctx["log"](s)
            except Exception:
                pass

    def _observe():
        elems = act_s = fp = None
        try:
            elems = ctx["get_elems"]() if ctx.get("get_elems") else None
        except Exception:
            elems = None
        try:
            act_s = ctx["get_activity"]() if ctx.get("get_activity") else ""
        except Exception:
            act_s = ""
        try:
            fp = ctx["get_fp"]() if ctx.get("get_fp") else None
        except Exception:
            fp = None
        return elems, act_s, fp

    steps = script.get("steps") or []
    if not steps:
        return False, "", log, 0

    for i, st in enumerate(steps, 1):
        do = str(st.get("do") or "")
        if do == "extract_rank":
            try:
                ans = (ctx.get("extract_rank") or (lambda n: ""))(int(st.get("n") or 5))
            except Exception as e:
                L("步骤 %d extract_rank 异常：%r" % (i, e))
                return False, "", log, i
            if not ans:
                L("步骤 %d extract_rank 未取到榜单数据" % i)
                return False, "", log, i
            return True, ans, log, 0
        if do == "extract_text":
            try:
                _rf = ctx.get("read_text")
                ans = _rf(str(st.get("text") or ""), st) if _rf else ""
            except Exception as e:
                L("步骤 %d extract_text 异常：%r" % (i, e))
                return False, "", log, i
            if not ans:
                L("步骤 %d extract_text 未读到内容" % i)
                return False, "", log, i
            # —— 本地合理性校验（0 模型也能查错；2026-10-11 新增）——
            #    sanity="today_date"：答案里必须出现"今天的 M月D日"
            #    （治"日历恢复到了别的月份、读到的不是今天"这类静默错答）
            _sn = str(st.get("sanity") or "")
            if _sn == "today_date":
                import datetime
                _d = datetime.date.today()
                _need = "%d月%d日" % (_d.month, _d.day)
                if _need not in ans:
                    L("步骤 %d 本地校验未过：答案里没有今天的日期（%s）→ 判失败" % (i, _need))
                    return False, "", log, i
            return True, ans, log, 0

        # ---- 执行 ----
        if do == "tap":
            tgt = st.get("spot") or st.get("text") or ""
            try:
                ok, err = (ctx.get("tap_spot") or (lambda n, s: (False, "no tap_spot")))(tgt, st)
            except Exception as e:
                ok, err = False, repr(e)
        else:
            act = {"action": do}
            for k, v in st.items():
                if k in ("do", "verify", "done"):
                    continue
                act[k] = v
            if do == "open_app" and not act.get("package"):
                act["package"] = script.get("app") or ""
            try:
                ok, err = ctx["do_action"](act)
            except Exception as e:
                ok, err = False, repr(e)
        if not ok:
            L("步骤 %d %s 执行失败：%s" % (i, do, err))
            return False, "", log, i

        # ---- 步后钩子（如 open_app 之后做起点归位）----
        if ctx.get("after_step"):
            try:
                ctx["after_step"](i, st)
            except Exception:
                pass

        # ---- 验收（三级锚点，最多两次机会）----
        ver = st.get("verify")
        if do == "open_app":
            # 打开应用这一步**一律改用 L1 硬锚点（包名）验收**：文本特征词是模型/固化时猜的，
            # 经常把"其实已经打开、只是不在首页"误判成失败（2026-10-12 实证：开盘啦脚本
            # 第 1 步就因首页特征词没命中而断裂）。
            _pkg = str(st.get("package") or script.get("app") or "")
            if _pkg:
                ver = {"activity": _pkg}
        # 纯包名锚点 + 读不到前台 Activity → 该锚点无法判定，直接跳过（不算失败、也不空转重试）
        if ver and isinstance(ver, dict) and set(ver) == {"activity"}:
            try:
                _a0 = ctx["get_activity"]() if ctx.get("get_activity") else ""
            except Exception:
                _a0 = ""
            if not _a0:
                L("步骤 %d 跳过包名锚点验收（读不到前台 Activity）" % i)
                ver = None
        if ver:
            got = False
            act_s = ""
            for attempt in range(3):
                if attempt:
                    time.sleep(1.5)
                elems, act_s, fp = _observe()
                if verify_anchors(ver, elems, act_s, fp):
                    got = True
                    break
            # 读不到前台 Activity（dumpsys 不可用 / ANCHORS 关闭）时，纯包名锚点无法判定
            # → 不因此判失败（"不确定就放行"；否则会把"其实打开了"误判成断裂）
            if not got and isinstance(ver, dict) and set(ver) == {"activity"} and not act_s:
                got = True
            if not got:
                L("步骤 %d 验收未通过（期望 %s）" % (i, json.dumps(ver, ensure_ascii=False)[:90]))
                return False, "", log, i

        if st.get("done"):
            return True, str(st.get("answer") or ""), log, 0

    # 跑完全部步骤却没产出答案 → 判为无效脚本（防"假完成"）
    L("脚本跑完但没有产出答案的步骤 → 判失败")
    return False, "", log, len(steps)


# ================================================================ 规划骨架编译（三段式：规划一次 → 执行到底）
_PLAN_DO = ("open_app", "tap", "input_text", "scroll", "swipe", "key", "wait", "read")


def compile_plan_steps(plan, app_pkg=""):
    """规划骨架 → 可重放步骤序列（replay 兼容）。

    背景（2026-10-12 重构）：用户要求「模型不常驻、不牺牲速度、每步必须正确」。
    所以模型只在**规划期介入一次**，产出"声明式"骨架——每步只说**做什么**（按元素名/
    关键词），不说坐标；执行期由 replay 在**当前屏幕上把目标解析成坐标**，逐条执行 + 逐条
    三级锚点核对（0 模型）。某步核对失败 → 交回模型恢复。常规步零模型调用。

    返回 [] = 规划没给出可执行骨架（此时才退回"每步问模型"的自由循环）。
    必须含"产出答案"的步骤，否则不执行（防假完成，2026-10-12 血泪）。
    """
    if not isinstance(plan, dict):
        return []
    raw = plan.get("steps")
    if not isinstance(raw, list):
        return []
    out = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        do = str(s.get("do") or "").strip().lower()
        if do not in _PLAN_DO:
            continue
        ver = s.get("verify")
        if isinstance(ver, list):
            ver = {"text": [str(x) for x in ver if x]}
        elif not isinstance(ver, dict):
            ver = None

        if do == "read":                                  # 读答案 → extract_rank / extract_text
            tgt = str(s.get("target") or "").strip()
            try:
                n = int(s.get("n") or 0)
            except Exception:
                n = 0
            if n > 0:
                st = {"do": "extract_rank", "n": n, "done": True}
            else:
                if not tgt:
                    continue
                st = {"do": "extract_text", "text": tgt, "done": True}
            if s.get("sanity"):
                st["sanity"] = str(s["sanity"])
            out.append(st)
            continue

        st = {"do": do}
        if do == "tap":
            cands = []
            tv = s.get("targets")
            if isinstance(tv, list):
                cands = [str(x).strip()[:40] for x in tv if str(x).strip()]
            tgt = str(s.get("target") or "").strip()[:40]
            if tgt and tgt not in cands:
                cands.insert(0, tgt)
            if not cands:
                continue
            st["text"] = cands[0]
            if len(cands) > 1:
                st["texts"] = cands[:5]          # 多候选：任一命中即可（模型猜的名字常对不上）
        elif do == "input_text":
            val = str(s.get("value") or s.get("target") or "")
            if not val:
                continue
            st["text"] = val[:120]
            st["clear"] = bool(s.get("clear", True))
        elif do == "open_app":
            st["package"] = str(s.get("package") or app_pkg or "")
            # 打开应用这一步**一律用 L1 硬锚点（包名）验收**，覆盖模型猜的特征词——
            # 模型猜的首页特征词经常不准，会把好任务误判成"没打开"（2026-10-12 实证：
            # 日历 open_app 期望 ["日历"] 而首页没这个词 → 骨架第 1 步就断）。
            if st["package"]:
                st["verify"] = {"activity": st["package"]}
                ver = None
        elif do in ("scroll", "swipe"):
            if s.get("direction"):
                st["direction"] = str(s["direction"])
            for k in ("x1", "y1", "x2", "y2", "duration"):
                if s.get(k) is not None:
                    st[k] = s[k]
        elif do == "key":
            st["key_code"] = int(s.get("key_code") or 4)
        elif do == "wait":
            st["seconds"] = float(s.get("seconds") or 1.5)
        if ver:
            st["verify"] = ver
        out.append(st)

    if not any(str(x.get("do")) in ("extract_rank", "extract_text") or x.get("done") for x in out):
        return []
    # 首步必须是"打开目标应用"（用 L1 硬锚点验收）；缺则补上，保证骨架一定从正确起点开始
    if app_pkg and (not out or str(out[0].get("do")) != "open_app"):
        out.insert(0, {"do": "open_app", "package": str(app_pkg),
                       "verify": {"activity": str(app_pkg)}})
    return out


def has_answer_in_steps(steps):
    """步骤序列里是否有"产出答案"的一步（与 has_answer_step 同义，作用于 steps 列表）。"""
    for st in (steps or []):
        if isinstance(st, dict) and (str(st.get("do") or "") in ("extract_rank", "extract_text")
                                     or st.get("done")):
            return True
    return False


# ================================================================ 成功即固化（候选脚本）
_LOG_TAP = re.compile(r"^tap\((\d+),(\d+)\)(?:→(.*))?$")
_LOG_OPEN = re.compile(r"^open_app\(([\w.\-]+)\)$")
_LOG_INPUT = re.compile(r"^input_text\((.*)\)$")
_LOG_KEY = re.compile(r"^key\((\d+)\)$")


def _slug(task):
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", (task or "").strip())
    s = re.sub(r"_+", "_", s).strip("_")[:28]
    return s or "script"


def save_candidate(task, plan=None, exec_log=None, family="", app="",
                   done_rejects=0, max_block_streak=0, elems_seq=None,
                   budget=None, d=None, max_steps_ratio=0.8):
    """任务成功后：把轨迹清洗压缩成"候选脚本"落盘。
    触发条件（任一不满足 → 返回 None）：
      ① 有执行轨迹 ② 步数 ≤ 家族预算 × max_steps_ratio ③ 无 done 驳回 ④ 最大连败 ≤1
    清洗：去 wait / 去连续重复的 scroll|swipe / 去"点击后弹出一次性弹窗"的步骤。
    返回写入的脚本 dict 或 None。
    """
    exec_log = exec_log or []
    if not exec_log:
        return None
    if done_rejects and int(done_rejects) > 0:
        return None
    if max_block_streak and int(max_block_streak) > 1:
        return None
    fam = family or match_family(plan or {}, task)
    bud = budget or budget_of(fam)
    if len(exec_log) > max(3, int(bud * max_steps_ratio)):
        return None

    steps = []
    for idx, line in enumerate(exec_log):
        s = str(line).strip()
        if s.endswith("（失败）"):
            continue                                  # 失败步不进脚本
        if s in ("wait", "done"):
            continue
        # 一次性弹窗清洗：该步点击后屏幕上出现了"跳过/我知道了/允许"类词
        if elems_seq and idx < len(elems_seq):
            post = elems_seq[idx] or []
            if any(any(w in str(e[3]) for w in POPUP_WORDS) for e in post):
                continue
        m = _LOG_OPEN.match(s)
        if m:
            steps.append({"do": "open_app", "package": m.group(1)})
            continue
        m = _LOG_TAP.match(s)
        if m:
            st = {"do": "tap", "xy": [int(m.group(1)), int(m.group(2))]}
            if m.group(3):
                st["text"] = m.group(3)[:20]
            steps.append(st)
            continue
        m = _LOG_INPUT.match(s)
        if m:
            steps.append({"do": "input_text", "text": m.group(1)[:40]})
            continue
        m = _LOG_KEY.match(s)
        if m:
            steps.append({"do": "key", "key_code": int(m.group(1))})
            continue
        if s.startswith("scroll_"):
            d2 = s.split("_", 1)[1] or "down"
            if steps and steps[-1].get("do") == "scroll" and steps[-1].get("direction") == d2:
                continue                              # 连续相同滚动合并
            steps.append({"do": "scroll", "direction": d2})
            continue
        if s.startswith("swipe("):
            if steps and steps[-1].get("do") == "swipe":
                continue
            steps.append({"do": "swipe"})
            continue
    if not steps:
        return None

    # 硬门槛：match 关键词为空 → 会命中一切任务（2026-10-12 劫持事故）→ 不固化
    kws = _keywords_of(task)
    if not kws:
        print("[agent] 脚本固化跳过：任务文本里提不出 match 关键词（空 match 会命中一切任务）")
        return None
    # 轨迹里没有"产出答案"的步骤 → 只能存成 draft（永不自动命中，待人工补读值步骤）
    has_ans = any(str(s.get("do") or "") in ("extract_rank", "extract_text") or s.get("done")
                  for s in steps)
    sid = _slug(task)
    sc = {"id": sid, "name": (task or "")[:30], "family": fam, "match": kws,
          "app": app or _app_of(steps), "steps": steps,
          "status": "candidate" if has_ans else "draft", "runs": 0, "ok": 0,
          "created": int(time.time()), "last_run": 0, "source_task": (task or "")[:60]}
    if not has_ans:
        sc["note"] = ("自动固化（draft）：轨迹里没有产出答案的步骤；"
                      "人工补一个 extract_text/extract_rank 后把 status 改成 candidate 才会生效")
    p = os.path.join(scripts_dir(d), sid + ".json")
    try:
        os.makedirs(scripts_dir(d), exist_ok=True)
        if os.path.exists(p):
            return None                               # 已存在同名 → 不覆盖（等人工/重放决策）
        with open(p, "w", encoding="utf-8") as f:
            json.dump(sc, f, ensure_ascii=False, indent=1)
    except Exception:
        return None
    return sc


def _app_of(steps):
    for st in steps:
        if st.get("do") == "open_app" and st.get("package"):
            return st["package"]
    return ""


def _keywords_of(task):
    t = re.sub(r"\s+", "", task or "")
    kws = []
    for _key, words in FAMILY_KEYWORDS:
        for w in words:
            if w in t and len(w) >= 2 and w not in kws:
                kws.append(w)
    return kws[:4]


def promote_candidate(sid, ok, d=None):
    """重放结果回写：成功 2 次 → active；失败 2 次 → deprecated。返回新状态或 None。"""
    p = os.path.join(scripts_dir(d), str(sid) + ".json")
    sc = _load_json(p, None)
    if not isinstance(sc, dict):
        return None
    sc["runs"] = int(sc.get("runs") or 0) + 1
    if ok:
        sc["ok"] = int(sc.get("ok") or 0) + 1
    sc["last_run"] = int(time.time())
    st = str(sc.get("status") or "candidate")
    fails = int(sc.get("runs") or 0) - int(sc.get("ok") or 0)
    if st == "candidate":
        if int(sc.get("ok") or 0) >= 2:
            st = "active"
        elif fails >= 2:
            st = "deprecated"
    elif st == "active" and fails >= 3:
        st = "deprecated"
    sc["status"] = st
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(sc, f, ensure_ascii=False, indent=1)
    except Exception:
        return None
    return st


# ================================================================ 子目标
def build_goals(plan):
    """plan.goals → [{"goal","verify","fallback"}]；缺失/非法 → []（退回旧行为）。"""
    g = (plan or {}).get("goals")
    if not isinstance(g, list):
        return []
    out = []
    for it in g:
        if not isinstance(it, dict):
            continue
        goal = str(it.get("goal") or "").strip()
        if not goal:
            continue
        ver = it.get("verify")
        if isinstance(ver, list):
            ver = {"text": [str(x) for x in ver if x]}
        elif not isinstance(ver, dict):
            ver = {}
        if not has_anchor(ver):
            ver = {}
        out.append({"goal": goal, "verify": ver, "fallback": str(it.get("fallback") or "")})
    return out


def has_anchor(ver):
    """锚点定义里是否有实际内容（空锚点 = 不验收）。"""
    if isinstance(ver, (list, tuple)):
        return any(str(x) for x in ver)
    if not isinstance(ver, dict):
        return False
    if ver.get("activity") or ver.get("fingerprint"):
        return True
    return any(str(t) for t in (ver.get("text") or []) if t)


def goal_hint(goals, idx):
    if not goals or idx < 0 or idx >= len(goals):
        return ""
    return "【当前子目标】%s（第 %d/%d 个）" % (goals[idx]["goal"], idx + 1, len(goals))


def goal_reached(goals, idx, elems=None, act="", fp=None):
    """当前子目标是否达成；verify 为空 → 视为"不验收"（返回 None 表示跳过）。"""
    if not goals or idx < 0 or idx >= len(goals):
        return None
    ver = goals[idx].get("verify")
    if not has_anchor(ver):
        return None
    return verify_anchors(ver, elems, act, fp)


# ================================================================ 硬闸门
GUARDS_BUILTIN = [
    {"id": "no_fake_pkg", "when": "open_app", "match": "不存在",
     "action": "block",
     "msg": "该包名本机不存在（已核对全部已安装应用）；请改用相关应用或搜索，不要臆造包名。"},
    {"id": "no_login_tap", "when": "tap", "match_danger": True,
     "action": "block", "msg": "安全规则：不操作登录/验证码/密码类元素。"},
]


def load_guards(d=None):
    """内置闸门 + 外部 guards.json；外部同 id 的规则**覆盖**内置（便于手机侧调参）。"""
    ext = _load_json(os.path.join(_skills_dir(d), "guards.json"), [])
    out = list(GUARDS_BUILTIN)
    if isinstance(ext, list):
        for g in ext:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or "")
            if gid:
                out = [x for x in out if str(x.get("id") or "") != gid]
            out.append(g)
    return out


def guard_check(act, ctx=None, guards=None, d=None):
    """执行前的硬闸门。返回 (block: bool, msg: str)。
    ctx 可含：pkg / page / label（tap 目标文字）/ err（上一次执行错误文案）。"""
    ctx = ctx or {}
    a = str((act or {}).get("action") or "")
    for g in (guards if guards is not None else load_guards(d)):
        when = str(g.get("when") or "")
        if when and when != a:
            continue
        app = g.get("app")
        if app and str(ctx.get("pkg") or "") != str(app):
            continue
        page = g.get("page")
        if page and str(ctx.get("page") or "") != str(page):
            continue
        if g.get("match_danger"):
            lbl = str(ctx.get("label") or (act or {}).get("pick") or "")
            if any(w in lbl for w in DANGER_WORDS):
                return True, str(g.get("msg") or "")
            continue
        m = str(g.get("match") or "")
        if m:
            hay = " ".join([json.dumps(act or {}, ensure_ascii=False),
                            str(ctx.get("err") or ""), str(ctx.get("label") or "")])
            if m not in hay:
                continue
        if str(g.get("action") or "") == "block":
            return True, str(g.get("msg") or "")
    return False, ""


# ================================================================ 失败归类
def classify_failure(stats):
    """失败归类 → (stage, pattern)。stats 可含：
    min_elems / plan_pkg / max_block_streak / open_app_fail / done_rejects /
    anchor_miss / errs(list) / last_err(str)"""
    s = stats or {}
    errs = [str(e) for e in (s.get("errs") or []) if e]
    last_err = str(s.get("last_err") or (errs[-1] if errs else ""))

    def pat(prefix):
        sig = re.sub(r"\d+", "N", last_err)[:40].strip()
        return "%s:%s" % (prefix, sig) if sig else prefix

    if int(s.get("min_elems") or 99) < 3:
        return "感知", pat("感知:元素不足")
    if int(s.get("anchor_miss") or 0) >= 5:
        return "锚点", pat("锚点:三级全不命中")
    if not str(s.get("plan_pkg") or "") and s.get("no_plan_app"):
        return "规划", pat("规划:未解析出目标应用")
    if int(s.get("done_rejects") or 0) >= 2:
        return "校验", pat("校验:done被驳回")
    if int(s.get("max_block_streak") or 0) >= 3:
        return "决策", pat("决策:动作被反复拒绝")
    if int(s.get("open_app_fail") or 0) >= 2:
        return "执行", pat("open_app")
    if last_err:
        return "执行", pat("执行:动作失败")
    return "未知", "未知"


# ================================================================ 感知健康度（2026-10-28）
# 阈值只在这里定义一处。mini_agent 的"感知边界提示"与"感知降级判定"都走这里，
# 避免提示词说 72%、降级判定用 50% 这种两套口径打架。
PERCEPT_X_HINT = 0.72    # 横向 < 72% → 提示模型"你只看了一部分"
PERCEPT_Y_HINT = 0.30    # 纵向 < 30% → 同上。阈值刻意压低：列表页元素天然集中在中间
                         # 一条带（上下是标题栏和留白），按 0.55 判会天天误报"纵向没看全"
PERCEPT_X_BAD = 0.50     # 横向 < 50% → 判定感知残缺，触发换通道/兜底
PERCEPT_MIN_ELEMS = 4    # 元素数 < 4 → 判定"树里没读到东西"


def percept_health(elems, screen_w=0, screen_h=0):
    """元素清单 → 感知健康度（纯计算，0 模型，可单测）。

    2026-10-28 新增。背景：酷安实测 a11y 树只覆盖屏宽 39%，但元素数有 20+，
    老规则"元素数 < 3 才算感知问题"直接漏判 —— 它有东西可读，只是读得不全。
    这类"半瞎"最容易被误读成"模型犯傻"，所以要把覆盖率和元素数分开记。

    返回 {"n": 元素数, "x_cov": 横向覆盖, "y_cov": 纵向覆盖,
          "level": "empty"|"bad"|"narrow"|"ok", "note": 中文短语}
    screen_w/screen_h 缺失时 x_cov/y_cov 记 0，level 只按元素数判。
    """
    try:
        es = list(elems or [])
    except Exception:
        es = []
    n = len(es)
    xs = [e[1] for e in es if len(e) > 2 and isinstance(e[1], int)]
    ys = [e[2] for e in es if len(e) > 2 and isinstance(e[2], int)]
    x_cov = y_cov = 0.0
    if xs and screen_w:
        x_cov = (max(xs) - min(xs)) / float(screen_w)
    if ys and screen_h:
        y_cov = (max(ys) - min(ys)) / float(screen_h)
    if n < PERCEPT_MIN_ELEMS:
        level, note = "empty", "树里几乎没读到元素"
    elif x_cov and x_cov < PERCEPT_X_BAD:
        level, note = "bad", "横向只看得到 %.0f%%" % (x_cov * 100)
    elif (x_cov and x_cov < PERCEPT_X_HINT) or (y_cov and y_cov < PERCEPT_Y_HINT):
        level, note = "narrow", "屏幕没看全"
    else:
        level, note = "ok", "覆盖正常"
    return {"n": n, "x_cov": round(x_cov, 3), "y_cov": round(y_cov, 3),
            "level": level, "note": note}


# ================================================================ 失败细类（2026-10-28）
# 与 classify_failure 的分工：
#   classify_failure → (stage, pattern)，回答"卡在哪一关"（感知/规划/决策/执行/校验/锚点）
#   classify_code    → (code, family, name)，回答"是哪一类毛病"，供报表聚合与硬闸门挖据
# 两者不互相替代：stage 用来看流程，code 用来看病种。
FAIL_CODE_NAMES = {
    "E-LOGIN":   ("环境", "需要登录"),
    "E-TIMEOUT": ("环境", "超时或预算耗尽"),
    "E-LAUNCH":  ("环境", "App 拉不起来"),
    "A-REJECT":  ("答案", "答案被复核驳回"),
    "P-EMPTY":   ("感知", "树里没读到元素"),
    "P-COVER":   ("感知", "屏幕没看全"),
    "P-BLIND":   ("感知", "往没有元素的地方点"),
    "D-LOOP":    ("决策", "动作被反复拒绝"),
    "D-ANCHOR":  ("决策", "页面身份认不出"),
    "X-UNKNOWN": ("未知", "未归类"),
}


def classify_code(stats):
    """失败细类判定 → (code, family, name)。

    stats 可含：login_wall(bool) / timeout(bool) / open_app_fail / done_rejects /
    min_elems / x_cov(float) / blind_taps / max_block_streak / anchor_miss
    优先级从"外因"到"内因"：环境 > 答案 > 感知 > 决策 > 未知。
    外因优先，是因为外因一旦成立，内因的统计就不可信（比如登录墙下点不动，
    不代表决策有问题）。
    """
    s = stats or {}

    def num(k, d=0):
        try:
            return int(s.get(k) or d)
        except Exception:
            return d

    if s.get("login_wall"):
        code = "E-LOGIN"
    elif s.get("timeout"):
        code = "E-TIMEOUT"
    elif num("open_app_fail") >= 2:
        code = "E-LAUNCH"
    elif num("done_rejects") >= 2:
        code = "A-REJECT"
    elif num("min_elems", 99) < PERCEPT_MIN_ELEMS:
        code = "P-EMPTY"
    elif float(s.get("x_cov") or 0) and float(s.get("x_cov") or 0) < PERCEPT_X_BAD:
        code = "P-COVER"
    elif num("blind_taps") >= 3:
        code = "P-BLIND"
    elif num("max_block_streak") >= 3:
        code = "D-LOOP"
    elif num("anchor_miss") >= 5:
        code = "D-ANCHOR"
    else:
        code = "X-UNKNOWN"
    fam, name = FAIL_CODE_NAMES.get(code, FAIL_CODE_NAMES["X-UNKNOWN"])
    return code, fam, name


# ================================================================ 开工可行性
def feasibility_check(plan, apps=None, task="", family="", elems=None):
    """开工前可行性 —— **只做高置信度拦截**（宁可放行，不可误拦）。

    2026-10-11 实证教训：早期版本把"规划器没产出"当成"听不懂"，导致
    LLM 短暂不可达时（ConnectionRefused）整条任务被误拦。现在只拦两种情况：
      ① 规划器**明确返回了**结果，但 intent / app / fallback 三者全空 → 确实没听懂
      ② 已在登录页 + 副作用任务（发送/发布）→ 需要先登录

    返回 (ok, reason, kind)；kind ∈ {"", "no_intent", "need_login"}。
    """
    plan = plan or {}
    # 规划阶段失败/未产出（plan 为空）→ **不拦**，交给自由循环（它会给出真实失败原因）
    if plan:
        if not str(plan.get("intent") or "").strip() \
                and not str(plan.get("app_package") or "").strip() \
                and not str(plan.get("fallback") or "").strip():
            return False, "没听懂这条任务（规划器没能理解），请再说一遍或换个说法", "no_intent"
    # 登录页**不再在开工时拦**（2026-10-12 用户口径：很多 App 只是弹一下登录，关掉就能继续用；
    # 一看到登录页就停是错的）。改由运行期处理：先关掉继续 → 反复出现才提醒用户登录。
    return True, "", ""


def login_wall(elems):
    """屏幕是否停在"登录墙"（真登录表单）。用于**早停**：目标 App 要求登录时，
    任何任务都无法继续 → 立刻如实报告，不烧步数（2026-10-12 实证：微博停在登录页，
    自由循环白烧 9 次模型调用 / 118 秒才报"无法查看"）。

    2026-10-22 修正（哔哩哔哩HD 实测误判）：
      原规则"≥3 个登录关键词"会把**首页右上角的「登录/注册」入口**当成登录墙，
      导致正常可浏览的首页被判死、任务 3 步就放弃。
      新规则分两级：
        · 强信号：出现「密码 / 验证码 / 手机号」等**表单字段** → 一定是登录页
        · 弱信号：只靠关键词，则要求 ≥6 个（首页导航罕有这么多登录相关词）
    """
    if not elems:
        return False
    texts = [str(e[3]) for e in elems]
    hit = sum(1 for t in texts if any(w in t for w in LOGIN_WORDS))
    if hit < 3:
        return False
    STRONG = ("密码", "验证码", "手机号", "手机号码", "账号密码", "其他登录方式",
              "同意用户协议", "同意并继续", "一键登录", "本机号码一键登录")
    if any(k in t for t in texts for k in STRONG):
        return True
    return hit >= 6


# ================================================================ 收工结果复核（治"莫名其妙的对错"）
def review_answer(task, answer, plan=None, family="", strict=False):
    """结果合理性复核 —— **规则优先，0 成本**（2026-10-12 新增）。

    用户要求「每个步骤都必须是正确的，防止莫名其妙的错误」。过程正确由每步三级锚点保证；
    答案正确由本函数兜底。只做**高置信度**判定：不确定时一律放行（返回 ok=True），
    把"要不要叫模型复核"的决定权交给调用方（strict=True 时调用方可再加一次模型复核）。

    返回 (ok, reason)；ok=False 表示答案**确定不合理**，应视为失败并交还。
    """
    a = str(answer or "").strip()
    if not a:
        return False, "空答案"
    if len(a) < 2:
        return False, "答案过短（<2 字）"
    if a in ("无法", "未知", "不知道", "无"):
        return False, "答案是无意义的占位词"

    t = str(task or "")
    NONE_WORDS = ("没有", "无", "暂无", "未设置", "未开启", "未找到", "空", "0 个", "0个")
    # 0) 答案不能是**过程叙述/意图**（2026-10-12 实证：B站任务模型把"当前屏幕显示的是推荐页，
    #    不是热门页，需要先点击热门标签"当成 done 的答案 → 被误判成功。这不是结果，是旁白。）
    NARRATION = ("当前屏幕显示", "需要先点", "需要先打开", "需要先进入", "需要先选择",
                 "接下来", "下一步", "应该先", "请先", "建议先", "尚未完成")
    if any(w in a for w in NARRATION):
        return False, "答案不是结果，而是过程叙述/意图说明"
    # 0.5) **方向一致性**：任务问"跌"、答案答"涨" → 判错。
    #      2026-10-12 血泪：任务「看今天跌停家数」被脚本匹配后答了「实际涨停: 36家」还判成功
    #      —— 这是最危险的"静默错答"，必须在收工复核里拦下。
    for _p, _q in (("涨停", "跌停"), ("上涨", "下跌"), ("增加", "减少"), ("开启", "关闭"),
                   ("已连接", "未连接"), ("买入", "卖出"), ("登录", "退出")):
        for _x, _y in ((_p, _q), (_q, _p)):
            if _x in t and _y in a and _x not in a:
                return False, "答案方向与任务相反（任务问「%s」，答案给的是「%s」）" % (_x, _y)
    # 1) 日期类：**只在答案里出现了日期、且不是今天**时才判错（治"日历停在上个月视图"）。
    #    不出现日期 → 不判（「今天没有日程」是合法答案，不能因为没有日期就驳回）。
    if any(w in t for w in ("今天", "日历", "日程", "几号", "日期")):
        try:
            import datetime
            d = datetime.date.today()
            found = re.findall(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", a)
            found += [(x[1], x[2]) for x in re.findall(r"\d{4}-(\d{1,2})-(\d{1,2})", a)]
            if found and not any(int(mo) == d.month and int(dy) == d.day for mo, dy in found):
                return False, "答案里的日期不是今天（今天是%d月%d日）" % (d.month, d.day)
        except Exception:
            pass
    # 1.5) **时间指向一致性**：任务问"明天/昨天/后天"，答案里的日期必须对得上。
    #      2026-10-12 血泪：任务「看**明天**的天气」被天气脚本匹配，答了**今天**的日期还判成功。
    if any(w in t for w in ("明天", "昨天", "后天")):
        try:
            import datetime
            d = datetime.date.today()
            _delta = 1 if "明天" in t else (-1 if "昨天" in t else 2)
            _want = d + datetime.timedelta(days=_delta)
            _found = re.findall(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", a)
            if _found and not any(int(mo) == _want.month and int(dy) == _want.day
                                  for mo, dy in _found):
                return False, ("答案的日期不是「%s」（应为 %d月%d日）"
                               % ("明天" if _delta == 1 else ("昨天" if _delta < 0 else "后天"),
                                  _want.month, _want.day))
        except Exception:
            pass
    # 2) 时间/闹钟类：答案里出现"时间样"内容却不是 HH:MM，或既无时间也无"没有"表述 → 判错
    if any(w in t for w in ("闹钟", "几点", "时间", "时钟")):
        if not re.search(r"\d{1,2}\s*[:：]\s*\d{2}", a) \
                and not any(w in a for w in NONE_WORDS):
            return False, "答案里没有时间格式（HH:MM）"
    # 3) 数值类：既无数字也无"没有"表述 → 判错
    if any(w in t for w in ("多少", "几个", "家数", "百分比", "电量", "温度", "涨", "跌")):
        if not re.search(r"\d", a) and not any(w in a for w in NONE_WORDS):
            return False, "答案里没有数字"
    # 4) 列表类**不做格式强制**（2026-10-12 修正）：
    #    早期版本要求"列表答案必须有序号/多行"，结果把**正确答案**「今天没有日程」连驳 5 次
    #    （日历任务被误判成 list，正确答案没有序号）→ 白烧 5 次模型调用。
    #    教训：规则只能抓"**确定错**"，抓不了"格式不合我意"。列表完整性由自由循环的
    #    wants_multi_answer + qwen_summary 负责，不在这里做。
    return True, ""


# ================================================================ 自检
def _selftest():
    ok = True

    def chk(name, cond):
        nonlocal ok
        print("%-46s %s" % (name, "PASS" if cond else "FAIL"))
        ok = ok and bool(cond)

    elems = [(0, 100, 100, "发现", True), (1, 500, 300, "微博热搜", False),
             (2, 300, 620, "实时热点", False), (3, 540, 2277, "首页", True),
             (4, 200, 400, "关注", True)]

    chk("anchor L3 双词命中", verify_anchors({"text": ["微博热搜", "关注"]}, elems))
    chk("anchor L3 单词不足", not verify_anchors({"text": ["微博热搜", "不存在词"]}, elems))
    chk("anchor 裸列表兼容", verify_anchors(["实时热点"], elems))
    chk("anchor 空", not verify_anchors({}, elems))

    cards = {"com.sina.weibo": normalize_card({
        "hint": "x",
        "home_path": {"back": 3, "until": ["发现"], "max_back": 5, "tap_home_tab": [540, 2277]},
        "pages": [{"name": "发现页", "verify": ["微博热搜", "关注"]},
                  {"name": "热搜榜", "verify": ["实时热点"]},
                  {"name": "搜索页", "verify": ["搜索微博", "取消"], "dead_end": True}],
        "spots": [{"label": "更多热搜", "x": 907, "y": 846, "whens": ["微博热搜"], "page": "发现页"},
                  {"label": "热搜", "x": 267, "y": 624, "whens": ["实时热点"], "page": "热搜榜"}]})}
    chk("page_id 发现页", page_id("com.sina.weibo", elems, "", None, cards) == "发现页")
    chk("need_home 在已知页→否", not need_home("com.sina.weibo", elems, "", None, cards))
    chk("need_home 未知页→是",
        need_home("com.sina.weibo", [(0, 1, 1, "别的东西", True)], "", None, cards))
    chk("need_home 死胡同页→是",
        need_home("com.sina.weibo",
                  [(0, 1, 1, "搜索微博", True), (1, 1, 1, "取消", True)], "", None, cards))
    chk("need_home 指定 target→是",
        need_home("com.sina.weibo", elems, "", None, cards, target=["热搜榜"]))
    chk("need_home 指定 target 命中→否",
        not need_home("com.sina.weibo", elems, "", None, cards, target=["发现页"]))
    chk("home_steps 有入口tab→只点tab（不用 BACK）",
        len(home_steps(cards["com.sina.weibo"])) == 1
        and home_steps(cards["com.sina.weibo"])[0]["action"] == "tap")
    chk("home_steps 无tab→有界 BACK（≤3）",
        len(home_steps({"home_path": {"back": 3, "until": ["x"], "max_back": 5}})) == 3
        and home_steps({"home_path": {"back": 2, "until": ["x"]}})[0]["action"] == "key")
    chk("home_steps 无tab无back→空",
        home_steps({"home_path": {"until": ["x"]}}) == [])
    chk("entry_pages = 发现页", entry_pages(cards["com.sina.weibo"]) == ["发现页"])

    # 卡片深合并（外部只给新字段，内置 hint/spots 保留）
    import tempfile
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, "scripts"), exist_ok=True)
    with open(os.path.join(tmp, "apps.json"), "w", encoding="utf-8") as _f:
        json.dump({"com.sina.weibo": {"version": 3,
                                      "home_path": {"back": 2, "until": ["发现"]}}}, _f)
    mc = cards_of({"com.sina.weibo": {"hint": "内置提示",
                                      "spots": [["更多热搜", 907, 846, ["微博热搜"]]]}}, d=tmp)
    chk("卡片深合并（hint/spots 保留 + home_path 生效）",
        mc["com.sina.weibo"]["hint"] == "内置提示"
        and int(mc["com.sina.weibo"]["home_path"]["back"]) == 2
        and len(mc["com.sina.weibo"]["spots"]) == 1)
    chk("卡片深合并（旧格式 spots 数组兼容）",
        mc["com.sina.weibo"]["spots"][0]["x"] == 907)

    co = app_coords2("com.sina.weibo", elems, "发现页", set(), cards)
    chk("坐标注入（页面匹配）", len(co) == 1 and co[0]["label"] == "更多热搜")
    co2 = app_coords2("com.sina.weibo", elems, "热搜榜", set(), cards)
    chk("坐标注入（换页换坐标）", len(co2) == 1 and co2[0]["label"] == "热搜")
    chk("坐标注入（失效名单）",
        app_coords2("com.sina.weibo", elems, "发现页",
                    {spot_key("com.sina.weibo", "更多热搜")}, cards) == [])
    chk("坐标注入（同名已在屏→不注入）",
        app_coords2("com.sina.weibo",
                    elems + [(9, 905, 845, "更多热搜", True)], "发现页", set(), cards) == [])

    chk("家族 send", match_family({}, "给exalex发条test") == "send")
    chk("家族 list", match_family({}, "微博热搜前五是什么") == "list")
    chk("家族 read", match_family({}, "打开设置看电池电量多少") == "read")
    chk("家族 plan 优先", match_family({"family": "search"}, "随便") == "search")
    chk("预算 read=15", budget_of("read") == 15)

    scs = [{"id": "a", "status": "active", "match": ["微博", "热搜"], "family": "list",
            "app": "com.sina.weibo", "runs": 4,
            "steps": [{"do": "open_app"}, {"do": "extract_rank", "n": 5, "done": True}]}]
    chk("脚本命中", (match_script("微博热搜前五", "list", "", None, scs) or {}).get("id") == "a")
    chk("脚本 family 不符不命中", match_script("微博热搜前五", "send", "", None, scs) is None)
    chk("脚本 candidate 未验证(ok=0)→不命中",
        match_script("微博热搜前五", "list", "", None,
                     [dict(scs[0], status="candidate", ok=0)]) is None)
    chk("脚本 candidate 已成功过(ok≥1)→命中",
        (match_script("微博热搜前五", "list", "", None,
                      [dict(scs[0], status="candidate", ok=1)]) or {}).get("id") == "a")
    chk("脚本 active 优先于 candidate",
        (match_script("微博热搜前五", "list", "", None,
                      [dict(scs[0], id="cand", status="candidate", runs=9, ok=9),
                       dict(scs[0], id="act", status="active", runs=1)]) or {}).get("id") == "act")
    chk("脚本 deprecated 不命中",
        match_script("微博热搜前五", "list", "", None,
                     [dict(scs[0], status="deprecated")]) is None)
    chk("脚本 draft 不命中",
        match_script("微博热搜前五", "list", "", None,
                     [dict(scs[0], status="draft")]) is None)
    chk("脚本 空 match 不命中（防劫持）",
        match_script("随便什么任务", "", "", None, [dict(scs[0], match=[])]) is None)
    chk("脚本 无答案步骤不命中（防假完成）",
        match_script("微博热搜前五", "list", "", None,
                     [dict(scs[0], steps=[{"do": "open_app"}])]) is None)
    chk("has_answer_step",
        has_answer_step({"steps": [{"do": "extract_text"}]})
        and has_answer_step({"steps": [{"do": "tap", "done": True}]})
        and not has_answer_step({"steps": [{"do": "tap"}]}))

    # replay：锚点不中 → 断点正确
    def mk_ctx(seq):
        box = {"i": 0}
        def get_elems():
            v = seq[min(box["i"], len(seq) - 1)]
            box["i"] += 1
            return v
        return {"get_elems": get_elems, "get_activity": lambda: "",
                "get_fp": lambda: None,
                "do_action": lambda act: (True, ""),
                "tap_spot": lambda n, s: (True, "")}
    script = {"id": "t", "app": "x", "steps": [
        {"do": "open_app", "verify": {"text": ["发现"]}},
        {"do": "tap", "spot": "更多热搜", "verify": {"text": ["微博热搜"]}},
        {"do": "extract_rank", "n": 5}]}
    ctx = mk_ctx([[ (0,1,1,"发现",True) ],
                  [ (0,1,1,"微博热搜",True) ],
                  [ (0,1,1,"榜单",True) ]])
    ctx["extract_rank"] = lambda n: "1. a 2. b"
    okr, res, lg, brk = replay(script, ctx)
    chk("replay 全通过", okr and res.startswith("1.") and brk == 0)

    # open_app 用 L1 包名锚点验收：Activity 可读时正常通过；Activity 读不到时跳过（不误判）
    _scA = {"id": "a", "app": "com.x", "steps": [{"do": "open_app"},
                                                 {"do": "extract_rank", "n": 2}]}
    _cA = mk_ctx([[]])
    _cA["get_activity"] = lambda: "com.x/com.x.MainActivity"
    _cA["extract_rank"] = lambda n: "1. a 2. b"
    chk("replay open_app 包名锚点命中", replay(_scA, _cA)[0] is True)
    _cB = mk_ctx([[]])
    _cB["get_activity"] = lambda: "com.other/com.other.Main"
    chk("replay open_app 包名不匹配→断", replay(_scA, _cB)[3] == 1)

    ctx2 = mk_ctx([[ (0,1,1,"发现",True) ],
                   [ (0,1,1,"没有目标词",True) ],
                   [ (0,1,1,"没有目标词",True) ],
                   [ (0,1,1,"没有目标词",True) ]])
    ctx2["extract_rank"] = lambda n: ""
    okr2, _r2, _l2, brk2 = replay(script, ctx2)
    chk("replay 断点=2", (not okr2) and brk2 == 2)

    # replay：跑完但无答案步骤 → 判失败（防"假完成"）
    _c3 = mk_ctx([[(0, 1, 1, "任意", True)]])
    _ok3, _r3, _l3, _b3 = replay({"id": "x", "app": "a", "steps": [{"do": "open_app"}]}, _c3)
    chk("replay 无答案步骤→失败", (not _ok3) and _b3 == 1)

    goals = build_goals({"goals": [{"goal": "回发现页", "verify": ["发现"]},
                                   {"goal": "读前五", "verify": []}]})
    chk("goals 构建", len(goals) == 2 and goals[0]["verify"]["text"] == ["发现"])
    chk("goals 空 verify", goal_reached(goals, 1, elems) is None)
    chk("goal_hint", "第 1/2 个" in goal_hint(goals, 0))
    chk("goals 缺失→[]", build_goals({}) == [])

    blk, msg = guard_check({"action": "open_app", "package": "com.x.y"},
                           {"err": "本机未安装该应用（包名 com.x.y 不存在"})
    chk("闸门 block 假包名", blk and "不存在" in msg)
    blk2, _ = guard_check({"action": "tap", "x": 1, "y": 2}, {"label": "获取验证码"})
    chk("闸门 block 验证码", blk2)
    blk3, _ = guard_check({"action": "tap", "x": 1, "y": 2}, {"label": "发现"})
    chk("闸门 放行正常点击", not blk3)

    st, pat = classify_failure({"min_elems": 1})
    chk("归类 感知", st == "感知")
    st2, _ = classify_failure({"min_elems": 40, "done_rejects": 2})
    chk("归类 校验", st2 == "校验")
    st3, pat3 = classify_failure({"min_elems": 40, "open_app_fail": 3,
                                  "last_err": "本机未安装该应用（包名 com.miui.weather"})
    chk("归类 执行 + pattern", st3 == "执行" and pat3.startswith("open_app"))

    # —— 感知健康度（2026-10-28）——
    _mid = [(i, 658 + i * 40, 300 + i * 20, "e%d" % i, True) for i in range(20)]
    h0 = percept_health([], 2160, 1350)
    chk("感知度 空清单→empty", h0["level"] == "empty")
    h1 = percept_health(_mid, 2160, 1350)
    chk("感知度 只覆盖中间 39%→bad（酷安实测形态）",
        h1["level"] == "bad" and 0.35 < h1["x_cov"] < 0.45)
    _full = [(i, 40 + (i % 10) * 210, 60 + (i // 10) * 700, "e%d" % i, True) for i in range(20)]
    h2 = percept_health(_full, 2160, 1350)
    chk("感知度 铺满→ok", h2["level"] == "ok")

    # —— 失败细类（2026-10-28）——
    chk("细类 登录墙优先", classify_code({"login_wall": True, "min_elems": 1})[0] == "E-LOGIN")
    chk("细类 覆盖不全（元素够多但只看到一半）",
        classify_code({"min_elems": 25, "x_cov": 0.39})[0] == "P-COVER")
    chk("细类 元素不足", classify_code({"min_elems": 2, "x_cov": 0.39})[0] == "P-EMPTY")
    chk("细类 盲点点击", classify_code({"min_elems": 30, "blind_taps": 4})[0] == "P-BLIND")
    chk("细类 未知兜底", classify_code({})[0] == "X-UNKNOWN")

    chk("可行性 规划缺失→不拦（防误拦）", feasibility_check({}, apps=[])[0] is True)
    chk("可行性 明确没听懂→拦",
        feasibility_check({"intent": "", "app_package": "", "fallback": ""})[0] is False)
    chk("可行性 有 intent→放行",
        feasibility_check({"intent": "看新闻", "app_package": "", "fallback": ""},
                          apps=[]) [0] is True)
    chk("可行性 有浏览器替代→放行",
        feasibility_check({"intent": "看新闻", "app_package": "", "fallback": "用浏览器搜索"},
                          apps=[]) [0] is True)
    chk("登录墙 3 词命中→是",
        login_wall([(0, 1, 1, "登录", True), (1, 1, 1, "验证码", True),
                    (2, 1, 1, "密码", True), (3, 1, 1, "首页", True)]) is True)
    chk("登录墙 2 词→否", login_wall([(0, 1, 1, "登录", True), (1, 1, 1, "密码", True)]) is False)
    chk("登录墙 空→否", login_wall([]) is False and login_wall(None) is False)
    chk("可行性 登录页**不拦**（改由运行期先关掉继续）",
        feasibility_check({"intent": "发消息", "app_package": "com.tencent.mm"},
                          family="send",
                          elems=[(0,1,1,"登录",True),(1,1,1,"验证码",True),(2,1,1,"密码",True)])[0] is True)

    # ---- 规划骨架编译（三段式）----
    _p1 = {"steps": [{"do": "open_app"}, {"do": "tap", "target": "热榜", "verify": ["热榜"]},
                     {"do": "read", "target": "热榜", "n": 3, "done": True}]}
    _c1 = compile_plan_steps(_p1)
    chk("compile 三步", len(_c1) == 3)
    chk("compile tap 用 text", _c1[1]["do"] == "tap" and _c1[1]["text"] == "热榜")
    chk("compile read(n)→extract_rank", _c1[2]["do"] == "extract_rank" and _c1[2]["n"] == 3)
    chk("compile 有答案步骤", has_answer_in_steps(_c1))
    _p2 = {"steps": [{"do": "open_app"}, {"do": "tap", "target": "X"}]}
    chk("compile 无答案步骤→拒（防假完成）", compile_plan_steps(_p2) == [])
    _p3 = {"steps": [{"do": "read", "target": "实际涨停"}]}
    _c3 = compile_plan_steps(_p3)
    chk("compile read 无 n→extract_text", _c3 and _c3[0]["do"] == "extract_text")
    chk("compile 非 dict/空→[]", compile_plan_steps(None) == [] and compile_plan_steps({}) == [])
    chk("compile tap 缺 target→跳过",
        compile_plan_steps({"steps": [{"do": "tap"}, {"do": "read", "n": 1}]}) ==
        [{"do": "extract_rank", "n": 1, "done": True}])
    _c5 = compile_plan_steps({"steps": [{"do": "read", "target": "电量", "done": True}]},
                             app_pkg="com.android.settings")
    chk("compile 自动补 open_app 首步", _c5[0]["do"] == "open_app"
        and _c5[0]["package"] == "com.android.settings")
    chk("compile open_app 用 L1 包名锚点", _c5[0]["verify"] == {"activity": "com.android.settings"})
    # 规划骨架可被 replay 直接执行（用假 ctx 走通）
    _c4 = compile_plan_steps({"steps": [{"do": "open_app"},
                                        {"do": "read", "target": "电量", "done": True}]})
    _c4[0]["package"] = "com.android.settings"
    _ctxp = mk_ctx([[(0, 1, 1, "任意", True)]])
    _ctxp["read_text"] = lambda t, st=None: "电量 88%"
    _okp, _resp, _lp, _bp = replay({"app": "com.android.settings", "steps": _c4}, _ctxp)
    chk("compile 产物可 replay 出答案", _okp and "88" in _resp)

    # ---- 收工结果复核 ----
    chk("复核 空答案→失败", review_answer("看电量", "")[0] is False)
    _td2 = __import__("datetime").date.today()
    _tmr = _td2 + __import__("datetime").timedelta(days=1)
    chk("复核 问明天答今天→失败",
        review_answer("看明天的天气怎么样",
                      "%d月%d日 周一 19到25度" % (_td2.month, _td2.day))[0] is False)
    chk("复核 问明天答明天→通过",
        review_answer("看明天的天气怎么样",
                      "%d月%d日 周二 20到26度" % (_tmr.month, _tmr.day))[0] is True)
    chk("复核 方向相反→失败（问跌停答涨停）",
        review_answer("打开开盘啦，看今天跌停家数", "实际涨停: 36家 (过滤ST股)")[0] is False)
    chk("复核 方向一致→通过",
        review_answer("打开开盘啦，看今天跌停家数", "实际跌停: 8家 (过滤ST股)")[0] is True)
    chk("脚本 not_match 排除",
        match_script("看今天跌停家数", "read", "", None,
                     [dict(scs[0], match=["开盘", "涨停"], not_match=["跌停"],
                           app="com.aiyu.kaipanla")]) is None)
    chk("复核 过程叙述→失败（不是答案）",
        review_answer("看B站热门榜前三", "当前屏幕显示的是“推荐”页，不是“热门”页。需要先点击顶部的“热门”标签才能看到热门榜。",
                      family="list")[0] is False)
    chk("复核 日期是别的日子→失败",
        review_answer("打开日历看今天日程", "已选中,09月01日 没有日程")[0] is False)
    import datetime as _dt
    _td = _dt.date.today()
    chk("复核 日期对→通过",
        review_answer("打开日历看今天日程", "%d月%d日 没有日程" % (_td.month, _td.day))[0] is True)
    chk("复核 无日期但有结论→通过（不误伤）",
        review_answer("打开日历看今天日程", "今天没有日程")[0] is True)
    chk("复核 闹钟无时间无否定→失败", review_answer("看我的闹钟", "起床闹铃")[0] is False)
    chk("复核 闹钟有时间→通过", review_answer("看我的闹钟", "07:00 起床闹铃")[0] is True)
    chk("复核 闹钟说没有→通过", review_answer("看我的闹钟", "没有设置闹钟")[0] is True)
    chk("复核 数值无数字→失败", review_answer("看电量多少", "电量充足")[0] is False)
    chk("复核 数值有数字→通过", review_answer("看电量多少", "88%")[0] is True)
    chk("复核 列表不做格式强制（防误伤正确答案）",
        review_answer("看热搜前五", "某条新闻标题", family="list")[0] is True
        and review_answer("打开日历看今天日程", "今天没有日程", family="list")[0] is True)
    chk("复核 普通任务不误伤", review_answer("打开设置", "设置")[0] is True)

    print("\n%s" % ("全部通过" if ok else "有失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
