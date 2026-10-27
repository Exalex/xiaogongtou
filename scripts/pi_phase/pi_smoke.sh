#!/data/data/com.termux/files/usr/bin/bash
# pi_smoke.sh — 手机侧 pi 首跑冒烟（root 身份）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
mkdir -p $HOME/bridge/out
OUT=$HOME/bridge/out/pi_smoke.out
PI=$HOME/pi-runtime/pi

echo "== 1) pi --version =="
$PI --version 2>&1

echo "== 2) pi -p smoke (dgx: bash echo) $(date +%T) =="
: > $OUT
"$PI" -p --no-session --provider dgx --model qwen3.8-flash-next \
  "用 bash 工具执行 echo PI_PHONE_OK，然后回复命令输出。" > $OUT 2>&1 &
BGPID=$!
N=0
while kill -0 $BGPID 2>/dev/null; do
  sleep 2; N=$((N+2))
  if [ $N -ge 240 ]; then
    echo "(watchdog: kill after ${N}s)"
    kill $BGPID 2>/dev/null
    break
  fi
done
wait $BGPID 2>/dev/null
echo "rc=$? elapsed~${N}s"
echo "== output =="
cat $OUT
echo "== done $(date +%T) =="
