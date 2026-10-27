#!/data/data/com.termux/files/usr/bin/bash
# pi_task_a.sh — P1 验收：pi 独立用 ptool 完成真实手机任务（读电量）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
mkdir -p $HOME/bridge/out
OUT=$HOME/bridge/out/pi_task_a.out
PI=$HOME/pi-runtime/pi

: > $OUT
"$PI" -p --no-session --provider dgx --model qwen3.8-flash-next \
  "用手机工具查看这台手机当前的电量和充电状态，报告 level 数字和是否在充电。工具提示：python3 ~/bridge/tools/ptool.py battery" \
  > $OUT 2>&1 &
BGPID=$!
N=0
while kill -0 $BGPID 2>/dev/null; do
  sleep 2; N=$((N+2))
  if [ $N -ge 300 ]; then echo "(watchdog kill ${N}s)"; kill $BGPID 2>/dev/null; break; fi
done
wait $BGPID 2>/dev/null
echo "rc=$? elapsed~${N}s"
echo "== output =="
cat $OUT
echo "== done $(date +%T) =="
