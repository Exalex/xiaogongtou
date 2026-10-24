#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""explore_app.py —— App 探索器：把某个 App 逛一遍，产出可复用的地图

设计取舍（2026-10-22）：
  · PC 驱动（走 portal HTTP）而不是设备端跑：改一行就能重跑，不用每次推文件
  · hub-and-spoke：回到首页 → 逐个点候选 → 每次点完按返回核对是否回到原页
    （比纯 BFS 稳：BFS 需要精确的"回上一页"，而返回键的行为各 App 不一样）
  · 只逛不操作：所有"花钱/改数据/发内容/账号"类点击一律跳过（DANGER）
  · 有预算：--minutes 时间上限 + --max-probes 次数上限，到点就收工保存

用法:
  python explore_app.py --pkg tv.danmaku.bilibilihd --minutes 6
  python explore_app.py --all --minutes 5 --max-apps 5      # 批量（空闲时跑）
  python explore_app.py --list                              # 看已有地图

产出: ~/bridge/skills/app_maps/<pkg>.json（格式见 appmap.py）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tabletbrain"))
import appmap  # noqa: E402

ADB = r"D:\workspace\workbuddySpace\githubResearch\.tools\platform-tools\adb.exe"
DEVICE = "192.168.3.93"
PORT = 8080

# 绝对不点：花钱 / 改数据 / 发内容 / 账号操作
DANGER = ("支付", "付款", "购买", "下单", "充值", "提现", "转账", "红包", "打赏",
          "删除", "清空", "格式化", "退出", "注销", "解绑", "卸载",
          "更新", "升级", "安装", "下载", "开始下载",
          "登录", "注册", "授权", "同意", "隐私", "权限", "实名", "认证", "签约",
          "开卡", "借钱", "贷款", "买入", "卖出", "撤单", "委托", "确认支付",
          "发送", "发布", "投稿", "上传", "开播", "分享", "举报", "拉黑",
          "重启", "恢复出厂", "清除数据")
# 弹窗类：点了只是关掉，不需要记录成边
DISMISS = ("跳过", "关闭", "知道了", "下次再说", "以后再说", "暂不", "取消", "不同意")


# ---------------------------------------------------------------- portal 客户端

def _adb(args, timeout=25):
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    try:
        r = subprocess.run([ADB] + args, capture_output=True, timeout=timeout, env=env)
        return (r.stdout or b"").decode("utf-8", "replace")
    except Exception:
        return ""


def fetch_token(serial=""):
    """从设备 shared_prefs 里取 portal token（每次重装都会变，不能写死）。"""
    xml = _adb(["shell", "/debug_ramdisk/su -c "
                "'cat /data/data/com.mobilerun.portal/shared_prefs/mobilerun_secrets.xml'"],
               timeout=30)
    m = re.search(r'name="auth_token"[^>]*>([^<]+)<', xml)
    return m.group(1).strip() if m else ""


class Portal:
    def __init__(self, token, host=DEVICE, port=PORT):
        self.base = "http://%s:%d" % (host, port)
        self.token = token

    def _req(self, path, method="GET", body=None, timeout=20):
        url = self.base + path
        data = None
        headers = {"Authorization": "Bearer " + self.token}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def raw_state(self):
        return self._req("/state_full", timeout=25).get("result") or {}

    def state(self):
        """→ (elems[(idx,cx,cy,label,clickable)], pkg, activity)"""
        d = self.raw_state()
        ps = d.get("phone_state") or {}
        elems = _flatten(d.get("a11y_tree") or {})
        return elems, ps.get("packageName") or "", ps.get("activityName") or ""

    def tap(self, x, y):
        try:
            self._req("/tap", "POST", {"x": int(x), "y": int(y)}, timeout=12)
        except Exception:
            pass

    def key(self, code):
        try:
            self._req("/keyboard/key", "POST", {"key_code": int(code)}, timeout=12)
        except Exception:
            pass

    def open_app(self, pkg):
        try:
            self._req("/app", "POST", {"package": pkg}, timeout=20)
        except Exception:
            pass


def _flatten(tree):
    """a11y 树 → [(序号, 中心x, 中心y, 文本, 可点)]，与 mini_agent 的格式对齐。"""
    out = []

    def walk(n):
        if not isinstance(n, dict):
            return
        lab = (n.get("text") or n.get("contentDescription") or "").strip()
        b = n.get("boundsInScreen") or {}
        if isinstance(b, dict) and b and (b.get("right", 0) > b.get("left", 0)):
            cx = (b.get("left", 0) + b.get("right", 0)) // 2
            cy = (b.get("top", 0) + b.get("bottom", 0)) // 2
            clk = bool(n.get("isClickable") or n.get("isLongClickable")
                       or n.get("isEditable"))
            if lab or clk:
                out.append((len(out), cx, cy, lab, clk))
        for c in n.get("children") or []:
            walk(c)

    walk(tree)
    return out


# ---------------------------------------------------------------- 探索逻辑

def wait_stable(p, before_hash=None, min_elems=5, timeout=12.0):
    """等界面稳定：连续两次采样哈希相同，且元素数达标。"""
    t0 = time.time()
    prev, stable = None, 0
    while time.time() - t0 < timeout:
        try:
            elems, pkg, act = p.state()
        except Exception:
            time.sleep(1.0)
            continue
        h = appmap.screen_hash(elems)
        if len(elems) >= min_elems and h == prev:
            stable += 1
            if stable >= 1:
                return elems, pkg, act, h
        else:
            stable = 0
        prev = h
        time.sleep(0.8)
    try:
        elems, pkg, act = p.state()
        return elems, pkg, act, appmap.screen_hash(elems)
    except Exception:
        return [], "", "", ""


def safe_candidates(elems, limit=8, skip_labels=()):
    """挑"安全且值得试"的点击候选 —— 按屏幕分区配额，不搞全局抢名额。

    两条实测修正（2026-10-24）：

    ① **不再要求元素被标记为"可点击"**
       酷安的「应用游戏」在 (1400,72)，a11y 里 clk=False，但它点了确实能切页。
       原来 `if not clk: continue` 直接把它筛掉了 —— 而这正是最有价值的入口。
       反正我们是按坐标点击，可点击标记只用来排序（可点的优先），不用来淘汰。

    ② **分区配额，而不是全局取前 N**
       原来一屏 8 个名额由整屏按分数抢，结果顶部导航入口被中间的"用户头像""图片1"挤掉。
       现在顶部条/底部条/中间区各分固定名额，保证每个导航区都有人代表。
    """
    h = 0
    for e in elems:
        if isinstance(e[2], int):
            h = max(h, e[2])

    zones = {"top": [], "bottom": [], "mid": []}
    used = set()
    for e in elems:
        idx, x, y, lab, clk = e
        if not lab:
            continue
        s = str(lab).strip()
        if len(s) < 2 or len(s) > 12:
            continue
        if y < 40:                       # 状态栏区域，不点
            continue
        if re.fullmatch(r"[\d\s.,:%+-]+", s):
            continue
        if re.search(r"\d{4,}", s):      # 播放量/价格这类
            continue
        if any(w in s for w in DANGER):
            continue
        # 纯控制键不是"入口"，点它只会回到上一页
        if any(w in s for w in ("返回", "后退", "上一步", "关闭", "取消", "收起")):
            continue
        if s in skip_labels or s in used:
            continue
        used.add(s)
        sc = appmap.nav_score(s, y, h)
        if not clk:
            sc -= 1.0                    # 没标可点击的排后面（但仍参赛）
        z = "top" if (h and y < h * 0.18) else ("bottom" if (h and y > h * 0.84) else "mid")
        zones[z].append((sc, x, y, s))

    for z in zones:
        zones[z].sort(key=lambda kv: -kv[0])

    # 顶部条通常有 4~5 个并列入口（个人主页/应用/通知/频道/搜索…），
    # 名额给少了会漏掉真正有用的那个（实测：酷安「应用游戏」就是这么被挤掉的）
    q = {"top": max(3, int(limit * 0.5)),
         "bottom": max(1, int(limit * 0.2)),
         "mid": max(1, limit - int(limit * 0.5) - int(limit * 0.2))}
    out, taken = [], set()
    for z in ("top", "mid", "bottom"):
        for item in zones[z][:q[z]]:
            out.append(item)
            taken.add(item[3])
    # 还有名额就从剩下的里按分数补齐
    if len(out) < limit:
        rest = [it for z in zones for it in zones[z] if it[3] not in taken]
        rest.sort(key=lambda kv: -kv[0])
        out.extend(rest[:limit - len(out)])
    out.sort(key=lambda kv: -kv[0])
    return [(x, y, s) for _sc, x, y, s in out[:limit]]


def dismiss_popups(p, elems, rounds=2):
    """点掉挡路的一次性弹窗（只点关闭类词）。"""
    n = 0
    for _ in range(rounds):
        hit = None
        for e in elems:
            s = str(e[3]).strip()
            if e[4] and s and len(s) <= 8 and any(w in s for w in DISMISS):
                hit = e
                break
        if not hit:
            break
        p.tap(hit[1], hit[2])
        n += 1
        time.sleep(1.0)
        elems, _pk, _ac = p.state()
    return n, elems


def reset_home(p, pkg, tries=2):
    """冷启到首页：唤醒 → 冷启 → 等稳定 → 清弹窗。"""
    # 设备可能熄屏/停在通知栏：先唤醒并解掉锁屏，否则拿到的是 systemui 的几根元素
    _adb(["shell", "input keyevent KEYCODE_WAKEUP"], timeout=15)
    _adb(["shell", "wm dismiss-keyguard"], timeout=15)
    time.sleep(0.8)
    for _ in range(tries):
        _adb(["shell", "/debug_ramdisk/su -c 'am force-stop %s'" % pkg], timeout=20)
        time.sleep(0.8)
        p.open_app(pkg)
        elems, cur, act, h = wait_stable(p, timeout=14.0)
        if cur != pkg:
            time.sleep(2.0)
            elems, cur, act, h = wait_stable(p, timeout=10.0)
        _n, elems = dismiss_popups(p, elems)
        if elems:
            elems, cur, act, h = wait_stable(p, timeout=8.0)
            return elems, cur, act, h
    return [], pkg, "", ""


def walk_to(p, pkg, path, st, verbose=False):
    """冷启回到首页，再按 path 逐标签点过去。每一步都用特征词核对。

    为什么不信"返回键"（实测）：B站的 tab 是**换内容不是进新页**，
    按返回键直接退出 App，根本回不到原来的页。
    "每次重走一遍"虽然多花 5~8 秒，但绝不会迷路，也不会污染数据。
    """
    elems = reset_home(p, pkg)[0]
    if not elems:
        return []
    for lab in path:
        tgt = None
        for c in safe_candidates(elems, limit=40):
            if c[2] == lab:
                tgt = c
                break
        if not tgt:
            if verbose:
                print("    （路径中断：找不到「%s」）" % lab)
            return []
        p.tap(tgt[0], tgt[1])
        elems = wait_stable(p, timeout=7.0)[0]
        _n, elems = dismiss_popups(p, elems)
    return elems


def probe_page(p, pkg, sid, elems, depth, path, st, verbose=True):
    """扫一页的候选：**每次都从首页重走一遍**再试下一个，绝不依赖返回键。

    判定分两个信号（实测教训）：
      · 变没变   → 整屏哈希（tab 切换也能抓到）
      · 变成哪页 → "父页 + 点的标签"做身份（内容刷新不影响）
    """
    tried = set()
    while len(tried) < st["max_per_page"] and st["probes"] < st["max_probes"] \
            and time.time() < st["deadline"]:
        cands = [c for c in safe_candidates(elems, limit=12, skip_labels=tried)
                 if c[2] not in tried]
        if not cands:
            break
        x, y, lab = cands[0]
        tried.add(lab)
        st["probes"] += 1

        before_full = appmap.screen_hash(elems)
        p.tap(x, y)
        el2, cur_pkg, _a2, _h2 = wait_stable(p, timeout=7.0)

        # —— 质量闸门 1：跑出目标 App 的一律作废 ——
        #    实测：B站首页会点到"酷安"推荐位、"下载管理"、系统权限框，
        #    这些一旦记进地图，任务时会把 agent 往别的 App 里带。
        if cur_pkg and cur_pkg != pkg:
            st["dead"].append({"from": sid, "tap": lab, "note": "跳出App:%s" % cur_pkg})
            if verbose:
                print("    「%s」→ 跳出到 %s（丢弃）" % (lab, cur_pkg))
            elems = walk_to(p, pkg, path, st) or []
            if not elems:
                return False
            continue

        # —— 质量闸门 2：系统权限框不是 App 的页面 ——
        _labels = " ".join(str(e[3]) for e in el2[:20])
        if any(k in _labels for k in ("仅在使用该应用时允许", "仅限这一次", "不允许",
                                      "允许访问", "权限申请")):
            st["dead"].append({"from": sid, "tap": lab, "note": "系统权限框"})
            if verbose:
                print("    「%s」→ 系统权限框（丢弃）" % lab)
            _n3, el2 = dismiss_popups(p, el2)
            elems = walk_to(p, pkg, path, st) or []
            if not elems:
                return False
            continue

        # —— 质量闸门 3：登录/协议页不是可复用的导航页 ——
        _labels4 = " ".join(str(e[3]) for e in el2[:25])
        if sum(1 for k in ("验证码", "手机号", "短信登录", "用户协议", "隐私政策",
                           "账号登录", "一键登录") if k in _labels4) >= 2:
            st["dead"].append({"from": sid, "tap": lab, "note": "登录/协议页"})
            if verbose:
                print("    「%s」→ 登录/协议页（丢弃）" % lab)
            elems = walk_to(p, pkg, path, st) or []
            if not elems:
                return False
            continue

        _n2, el2 = dismiss_popups(p, el2)
        after_full = appmap.screen_hash(el2)

        if after_full and after_full != before_full:
            nid = appmap.path_node_id(sid, lab)
            k2 = appmap.page_keys(el2)
            parent_keys = (st["screens"].get(sid) or {}).get("keys") or []
            d2 = appmap.distinct_keys(k2, parent_keys)
            # 内容去重：独有词和某个已知页几乎一样 → 就是同一页，复用它的 id。
            # （实测：从登录页按返回回到首页，会因为父页不同而被记成"新首页"。）
            if len(d2) >= 2:
                for _oid, _on in st["screens"].items():
                    _od = set(_on.get("distinct") or [])
                    if len(_od) >= 2:
                        _j = len(_od & set(d2)) / float(len(_od | set(d2)))
                        if _j >= 0.8:
                            nid = _oid
                            break
            new = nid not in st["screens"]
            if new:
                st["screens"][nid] = {
                    "keys": k2,
                    "distinct": d2,
                    "activity": "",
                    "path": path + [lab],
                    "name": lab,
                }
            st["edges"].append({"from": sid, "tap": lab, "to": nid})
            if verbose:
                d = (st["screens"].get(nid) or {}).get("distinct") or []
                print("    「%s」→ %s %s  独有词=%s"
                      % (lab, "新页" if new else "已知页", nid, d[:4]))
            if new and (depth + 1) < st["max_depth"]:
                probe_page(p, pkg, nid, el2, depth + 1, path + [lab], st, verbose)
        else:
            st["dead"].append({"from": sid, "tap": lab})
            if verbose:
                print("    「%s」→ 无变化（死路）" % lab)

        if len(tried) < st["max_per_page"] and st["probes"] < st["max_probes"] \
                and time.time() < st["deadline"]:
            elems = walk_to(p, pkg, path, st) or []
            if not elems:
                if verbose:
                    print("    （回不到本页，这一支到此为止）")
                return False
    return True


def explore(p, pkg, max_depth=2, max_probes=90, minutes=8.0, verbose=True, label=""):
    t_start = time.time()
    st = {
        "deadline": t_start + minutes * 60.0,
        "max_probes": max_probes,
        "max_per_page": 8,
        "probes": 0,
        "screens": {},
        "edges": [],
        "dead": [],
        "max_depth": max_depth if max_depth > 0 else 2,
    }

    elems, cur, act = reset_home(p, pkg)[:3]
    if not elems:
        print("[explore] 启动失败，放弃")
        return None

    home = appmap.node_id(elems)
    st["screens"][home] = {
        "keys": appmap.page_keys(elems), "distinct": [], "activity": act,
        "path": [], "name": "首页",
    }
    if verbose:
        print("[explore] 首页 %s 特征词=%s" % (home, st["screens"][home]["keys"]))

    probe_page(p, pkg, home, elems, 0, [], st, verbose)

    screens, edges, dead = st["screens"], st["edges"], st["dead"]
    probes = st["probes"]

    m = {
        "format": appmap.FORMAT,
        "pkg": pkg,
        "label": label or pkg,
        "exploredAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "durationSec": int(time.time() - t_start),
        "probes": probes,
        "home": home,
        "screens": screens,
        "edges": edges,
        "dead": dead,
    }
    m["entries"] = appmap.build_entries(home, edges)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-apps", type=int, default=3)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--max-probes", type=int, default=80)
    ap.add_argument("--minutes", type=float, default=6.0)
    ap.add_argument("--host", default=DEVICE)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--token", default="")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        ms = appmap.list_maps()
        if not ms:
            print("还没有任何 App 地图")
        for pkg, s in sorted(ms.items()):
            print("%-42s %2d页 %2d入口  %s" % (pkg, s["screens"], s["entries"], s["exploredAt"]))
        return

    token = args.token or fetch_token()
    if not token:
        print("[explore] 拿不到 portal token（设备未连？）")
        return
    p = Portal(token, args.host, args.port)

    pkgs = []
    labels = {}
    if args.pkg:
        pkgs = [args.pkg]
    elif args.all:
        try:
            apps = p._req("/packages", timeout=25)
            lst = apps.get("result") if isinstance(apps, dict) else apps
            if isinstance(lst, str):
                lst = json.loads(lst)
            skip = ("com.android.", "com.google.android.", "com.mobilerun.",
                    "com.termux", "com.topjohnwu.magisk", "com.xiaogongtou.")
            for a in lst or []:
                pkg = str(a.get("packageName") or "")
                if a.get("label"):
                    labels[pkg] = str(a.get("label"))
                if pkg and not pkg.startswith(skip):
                    pkgs.append(pkg)
            pkgs = pkgs[:args.max_apps]
        except Exception as e:
            print("[explore] 取应用列表失败: %r" % (e,))
            return
    else:
        # 单个 --pkg 也要能补上应用名
        try:
            apps = p._req("/packages", timeout=25)
            lst = apps.get("result") if isinstance(apps, dict) else apps
            if isinstance(lst, str):
                lst = json.loads(lst)
            for a in lst or []:
                if a.get("packageName") and a.get("label"):
                    labels[str(a["packageName"])] = str(a["label"])
        except Exception:
            pass

    for pkg in pkgs:
        print("\n===== 探索 %s =====" % pkg)
        try:
            m = explore(p, pkg, max_depth=args.depth,
                        max_probes=args.max_probes, minutes=args.minutes,
                        label=labels.get(pkg, ""))
            if m:
                path = appmap.save_map(m)
                print("[explore] 已保存 %s" % path)
                print("[explore] %s" % appmap.stats(m))
        except KeyboardInterrupt:
            print("[explore] 用户中断")
            break
        except Exception as e:
            print("[explore] %s 探索失败: %r" % (pkg, e))


if __name__ == "__main__":
    main()
