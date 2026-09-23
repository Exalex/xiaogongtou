#!/system/bin/sh
# uidump-bridge.sh —— root 常驻：把 uiautomator dump 的"完整无障碍树"桥给 Termux 侧的 agent
# 用途：portal 的 a11y 树会过滤掉被标记"不重要"的视图（如微博信息流），uiautomator 抓的树更全。
# 协议：agent 写 ~/bridge/.uidump_req（内容=时间戳）→ 本脚本 dump 到 ~/bridge/.uidump.xml（chown 给 Termux）
T=/data/data/com.termux/files/home/bridge
REQ=$T/.uidump_req
OUT=$T/.uidump.xml
last=""
mkdir -p "$T"
while true; do
  if [ -f "$REQ" ]; then
    v=$(cat "$REQ" 2>/dev/null)
    if [ -n "$v" ] && [ "$v" != "$last" ]; then
      uiautomator dump --compressed "$OUT" >/dev/null 2>&1
      chown 10353:10353 "$OUT" 2>/dev/null
      chmod 644 "$OUT" 2>/dev/null
      last="$v"
    fi
  fi
  sleep 0.15
done
