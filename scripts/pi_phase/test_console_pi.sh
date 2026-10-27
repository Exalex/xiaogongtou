#!/system/bin/sh
# test_console_pi.sh — P2 验收：控制台路由一个 Pi 任务并拿到结果
P=/data/data/com.termux/files/usr
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

echo "== POST /api/run (mode=pi) $(date +%T) =="
curl -s -X POST http://127.0.0.1:8900/api/run -H 'Content-Type: application/json' \
  -d '{"task":"读取当前电量和充电状态并简要报告。","mode":"pi"}'
echo
sleep 3
echo "== poll status =="
i=0
while [ $i -lt 70 ]; do
  S=$(curl -s http://127.0.0.1:8900/api/status)
  ST=$(echo "$S" | grep -o '"state": "[a-z]*"' | head -1)
  echo "[$i] $ST"
  case "$S" in
    *'"state": "done"'*|*'"state": "failed"'*|*'"state": "stopped"'*)
      echo "$S" | head -c 1500; echo; break;;
  esac
  i=$((i+1))
  sleep 4
done
echo "== done $(date +%T) =="
