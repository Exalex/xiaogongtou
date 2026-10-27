#!/system/bin/sh
# test_round2.sh — 修复后双测：auto（路由修复）与 Pi（新模式）同跑用户原句
P=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

echo "== entry app proc =="
pgrep -f "com.xiaogongtou.entry" | head -3

/system/bin/input keyevent 3
sleep 1

run_and_wait() {
  MODE="$1"; TASK="$2"
  echo "== [$MODE] $TASK  $(date +%T) =="
  curl -s -X POST http://127.0.0.1:8900/api/run -H 'Content-Type: application/json' \
    -d "{\"task\":\"$TASK\",\"mode\":\"$MODE\"}"
  echo
  i=0
  while [ $i -lt 90 ]; do
    S=$(curl -s http://127.0.0.1:8900/api/status)
    case "$S" in
      *'"state": "done"'*|*'"state": "failed"'*|*'"state": "stopped"'*) break;;
    esac
    i=$((i+1))
    sleep 4
  done
  echo "$S" | head -c 1400
  echo
  sleep 2
}

run_and_wait auto "呃，发条微信给EXLEX test。"
run_and_wait pi "呃，发条微信给EXLEX test。"
echo "== all done $(date +%T) =="
