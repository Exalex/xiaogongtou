#!/system/bin/sh
# xgt-bridge.sh —— root 常驻桥：为 Termux 侧 agent 提供两类能力
#  1) tree：向「小工头」App 请求完整 a11y 树（含"不重要"视图，如微博信息流）
#     —— 替代 uiautomator（实测：uiautomator dump 会触发系统解绑 portal 的 a11y 服务）
#  2) input 操作：tap / swipe / key / open —— portal 掉线时的操作容灾
# 协议：agent 写 ~/bridge/.xgt_req（内容 "<seq> <op> [args...]"）→ 本脚本执行 → 写 ~/bridge/.xgt_res（"ok"/"err:..."）
T=/data/data/com.termux/files/home/bridge
EXT=/data/media/0/Android/data/com.xiaogongtou.entry/files
REQ=$T/.xgt_req
RES=$T/.xgt_res
last=""
mkdir -p "$T"
while true; do
  if [ -f "$REQ" ]; then
    cmd=$(cat "$REQ" 2>/dev/null)
    if [ -n "$cmd" ] && [ "$cmd" != "$last" ]; then
      last="$cmd"
      set -- $cmd
      seq=$1
      op=$2
      shift 2
      case "$op" in
        tree)
          mkdir -p "$EXT" 2>/dev/null
          echo "$seq" > "$EXT/tree_req"
          ok=""
          i=0
          while [ $i -lt 40 ]; do
            if grep -q "$seq" "$EXT/tree.json" 2>/dev/null; then
              ok=1
              break
            fi
            sleep 0.1
            i=$((i+1))
          done
          if [ -n "$ok" ]; then
            cp "$EXT/tree.json" "$T/.tree.json"
            chown 10353:10353 "$T/.tree.json" 2>/dev/null
            chmod 644 "$T/.tree.json" 2>/dev/null
            echo "ok" > "$RES"
          else
            echo "err: tree timeout" > "$RES"
          fi
          ;;
        tap)
          input tap $1 $2 && echo "ok" > "$RES" || echo "err: input tap" > "$RES"
          ;;
        swipe)
          input swipe $1 $2 $3 $4 ${5:-500} && echo "ok" > "$RES" || echo "err: input swipe" > "$RES"
          ;;
        key)
          input keyevent $1 && echo "ok" > "$RES" || echo "err: input key" > "$RES"
          ;;
        open)
          monkey -p $1 -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 && echo "ok" > "$RES" || echo "err: open $1" > "$RES"
          ;;
        *)
          echo "err: unknown op" > "$RES"
          ;;
      esac
      chown 10353:10353 "$RES" 2>/dev/null
      chmod 644 "$RES" 2>/dev/null
    fi
  fi
  sleep 0.12
done
