#!/system/bin/sh
# shadow.sh —「影子屏管家」v1（开屏 / 状态 / 关屏）
# 影子屏 = 手机自己在后台开的无头虚拟屏（scrcpy-server 4.1 + 哑客户端，均为本机进程，不依赖 PC）。
# 用法: sh shadow.sh start | stop | status
# 开关文件: /data/adb/mobilerun-console/shadow.on （存在=守护保持影子屏常开）

H=/data/data/com.termux/files/home
ADIR=/data/adb/mobilerun-console
JAR=$ADIR/scrcpy-server-4.1.jar
PY=/data/data/com.termux/files/usr/bin/python3
SCID=05ad0001
SLOG=/data/local/tmp/shadow_server.log
CLOG=/data/local/tmp/shadow_client.log
ON=$ADIR/shadow.on

server_alive() { pgrep -f "scrcpy.[S]erver 4.1" >/dev/null 2>&1; }
client_alive() { pgrep -f "shadow_[c]lient.py" >/dev/null 2>&1; }

# 从服务端日志拿 display id（start 流程刚清过日志，故此时是新鲜的）
log_id() {
  grep -o "New display: [0-9]*x[0-9]*/[0-9]* (id=[0-9]*)" $SLOG 2>/dev/null | tail -1 | sed -n 's/.*id=\([0-9]*\)).*/\1/p'
}

# 以 dumpsys 为准探测影子屏是否真实存在（返回 id 或空）
live_id() {
  dumpsys display 2>/dev/null | grep -o "displayId=[0-9]*, uniqueId='virtual:[^']*scrcpy[^']*'" | head -1 | sed -n 's/displayId=\([0-9]*\).*/\1/p'
}

kill_all() {
  pkill -f "shadow_[c]lient.py" 2>/dev/null
  pkill -f "scrcpy.[S]erver 4.1" 2>/dev/null
  pkill -f "scrcpy.[C]leanUp" 2>/dev/null
}

start() {
  ID=$(live_id)
  if [ -n "$ID" ] && server_alive && client_alive; then
    echo "shadow up: id=$ID (already)"
    return 0
  fi
  kill_all
  sleep 1
  : > $SLOG
  : > $CLOG
  # 1) 服务端：监听 scrcpy_<scid>（tunnel_forward），等待 video+control 两条连接后才建屏
  (
    unset LD_LIBRARY_PATH LD_PRELOAD
    CLASSPATH=$JAR setsid /system/bin/app_process / com.genymobile.scrcpy.Server 4.1 \
      scid=$SCID tunnel_forward=true log_level=info \
      audio=false control=true video=true \
      max_fps=5 video_bit_rate=2000000 \
      new_display=1080x2400/480 \
      </dev/null >>$SLOG 2>&1 &
  )
  sleep 1
  # 2) 哑客户端：连 video+control 并把流读丢（让建屏完成并保持）
  (
    export TERMUX_PREFIX=/data/data/com.termux/files/usr
    export HOME=/data/data/com.termux/files/home
    export PATH=$TERMUX_PREFIX/bin:$PATH
    export LD_LIBRARY_PATH=$TERMUX_PREFIX/lib
    export LANG=en_US.UTF-8
    setsid $PY $H/shadow_client.py $SCID </dev/null >>$CLOG 2>&1 &
  )
  i=0
  while [ $i -lt 30 ]; do
    ID=$(log_id)
    [ -z "$ID" ] && ID=$(live_id)
    if [ -n "$ID" ]; then
      echo "shadow up: id=$ID"
      return 0
    fi
    sleep 0.6
    i=$((i+1))
  done
  echo "shadow: ERROR display not created"
  echo "--- server log ---"; tail -10 $SLOG 2>/dev/null
  echo "--- client log ---"; tail -6 $CLOG 2>/dev/null
  return 1
}

stop() {
  kill_all
  i=0
  while [ $i -lt 16 ]; do
    [ -z "$(live_id)" ] && { echo "shadow down"; return 0; }
    sleep 0.5
    i=$((i+1))
  done
  echo "shadow: WARN display still present id=$(live_id)"
  return 1
}

status() {
  if [ -f $ON ]; then echo "on=1"; else echo "on=0"; fi
  echo "id=$(live_id)"
  if server_alive; then echo "server=1"; else echo "server=0"; fi
  if client_alive; then echo "client=1"; else echo "client=0"; fi
}

case "$1" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: sh shadow.sh start|stop|status" ;;
esac
