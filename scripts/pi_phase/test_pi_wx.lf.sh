#!/system/bin/sh
# test_pi_wx.sh — P1 验收（微信）：
#   A) ptool wx-send 干净停路径（不存在的目标 → 0 点击 0 输入，rc=6）
#   B) pi 独立完成「给 exalex 发 test」（走 ptool wx-send 安全链）
P=/data/data/com.termux/files/usr
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

echo "== A) clean-stop probe (target not exist) $(date +%T) =="
python3 $HOME/bridge/tools/ptool.py wx-send --to "不存在的目标XYZ测试" --text "test" 2>&1 | tail -6
echo "A_rc=$?"

echo "== B) pi task: 给 exalex 发 test $(date +%T) =="
curl -s -X POST http://127.0.0.1:8900/api/run -H 'Content-Type: application/json' \
  -d '{"task":"给 exalex 发一条微信，内容：test","mode":"pi"}'
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
echo "$S" | head -c 1200
echo
echo "== done $(date +%T) =="
