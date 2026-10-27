#!/system/bin/sh
# final_check.sh — P2 最终验收：pi 任务 + 会话审计落盘
P=/data/data/com.termux/files/usr
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

echo "== pi task via console $(date +%T) =="
curl -s -X POST http://127.0.0.1:8900/api/run -H 'Content-Type: application/json' \
  -d '{"task":"读取当前电量并简要报告（数字即可）。","mode":"pi"}'
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
echo "$S" | head -c 900
echo
echo "== sessions (new since deploy) =="
ls -la /data/data/com.termux/files/home/.pi/agent/sessions/ 2>&1 | head -8
find /data/data/com.termux/files/home/.pi/agent/sessions -name "*.jsonl" -newer /data/local/tmp/deploy_p2c.lf.sh 2>/dev/null | head -3
echo "== done $(date +%T) =="
