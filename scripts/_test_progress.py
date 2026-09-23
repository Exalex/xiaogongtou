# -*- coding: utf-8 -*-
"""离线单测：mini_agent.Progress 的"持续无进展"判定逻辑（PC 侧运行）"""
import sys

sys.path.insert(0, r"D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/scripts")
from mini_agent import Progress

ok_all = True


def check(name, cond, extra=""):
    global ok_all
    print(("PASS  " if cond else "FAIL  ") + name + (("  | " + extra) if extra else ""))
    if not cond:
        ok_all = False


# 场景1：正常推进（动作不同、屏幕在变）→ 不误报
p = Progress()
for a, ok, h in [
    ({"action": "tap", "x": 100, "y": 200}, True, 111),
    ({"action": "tap", "x": 300, "y": 500}, True, 222),
    ({"action": "scroll", "direction": "down"}, True, 333),
    ({"action": "tap", "x": 400, "y": 700}, True, 444),
]:
    p.note(a, ok, h)
check("正常推进不误报", p.score == 0, "score=%d" % p.score)

# 场景2：点错东西 → 返回 → 再点同一个 → 循环（"伪 Settings"场景）
p = Progress()
scores = []
for a, ok, h in [
    ({"action": "tap", "x": 663, "y": 313}, True, 1),
    ({"action": "key", "key_code": 4}, True, 2),
    ({"action": "tap", "x": 663, "y": 313}, True, 1),
    ({"action": "key", "key_code": 4}, True, 2),
    ({"action": "tap", "x": 663, "y": 313}, True, 1),
]:
    p.note(a, ok, h)
    scores.append(p.score)
check("点-返回循环会累计无进展", scores[-1] >= 3, "scores=%s" % scores)

# 场景3：执行连续失败
p = Progress()
for i in range(3):
    p.note({"action": "tap", "x": 10 * i, "y": 10 * i}, False, 900 + i)
check("连续执行失败累计", p.score >= 3, "score=%d" % p.score)

# 场景4：屏幕长时间无变化（wait）
p = Progress()
for i in range(6):
    p.note({"action": "wait"}, True, 777)
check("屏幕无变化累计", p.score >= 1, "score=%d" % p.score)

# 场景5：一次出错后恢复正常 → 分数回血
p = Progress()
p.note({"action": "tap", "x": 1, "y": 1}, False, 1)
for i in range(4):
    p.note({"action": "tap", "x": 100 + i * 50, "y": 200 + i * 40}, True, 10 + i)
check("恢复后回血", p.score == 0, "score=%d" % p.score)

# 场景6：连续滚动（长列表）不误判
p = Progress()
for i in range(5):
    p.note({"action": "scroll", "direction": "down"}, True, 500 + i)
check("连续滚动不误判", p.score == 0, "score=%d" % p.score)

print("=" * 34)
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)
