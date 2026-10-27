#!/system/bin/sh
# test_pi_retry.sh — 指引更新后：Pi 重跑用户原句（期望：先尝试 wx-send 再报结论）
P=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

echo "== [pi] 呃，发条微信给EXLEX test。  $(date +%T) =="
curl -s -X POST http://127.0.0.1:8900/api/run -H 'Content-Type: application/json' \
  -d '{"task":"呃，发条微信给EXLEX test。","mode":"pi"}'
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
echo "$S" | head -c 2000
echo
echo "== done $(date +%T) =="
