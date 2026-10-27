#!/system/bin/sh
# verify_v2b.sh — 双轨回归：auto（老链路）与 pi（新链路）各跑一个任务
P=/data/data/com.termux/files/usr
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

run_and_wait() {
  MODE="$1"; TASK="$2"
  echo "== [$MODE] $TASK =="
  curl -s -X POST http://127.0.0.1:8900/api/run -H 'Content-Type: application/json' \
    -d "{\"task\":\"$TASK\",\"mode\":\"$MODE\"}"
  echo
  i=0
  while [ $i -lt 80 ]; do
    S=$(curl -s http://127.0.0.1:8900/api/status)
    case "$S" in
      *'"state": "done"'*|*'"state": "failed"'*|*'"state": "stopped"'*) break;;
    esac
    i=$((i+1))
    sleep 3
  done
  echo "$S" | head -c 1000
  echo
  sleep 2
}

run_and_wait auto "读一下当前电量并报告。"
run_and_wait pi "用 bash 执行 echo REG_OK，然后回复命令输出。"
echo "== all done $(date +%T) =="
