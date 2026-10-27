#!/data/data/com.termux/files/usr/bin/bash
# start_console3.sh — 用显式环境启动 mini_console（解决 HOME 丢失 -> /bridge 只读问题）
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin:/system/xbin
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp
export LANG=en_US.UTF-8
export PYTHONUNBUFFERED=1

cd "$HOME" || exit 1

# 确认 HOME 生效
if [ "$HOME" != "/data/data/com.termux/files/home" ]; then
  echo "FATAL: HOME not set correctly: $HOME"; exit 2
fi

mkdir -p "$HOME/bridge/out" "$HOME/bridge/runs" "$HOME/bridge/skills" "$HOME/bridge/examples"
LOG="$HOME/bridge/out/console.log"

pkill -f mini_console.py 2>/dev/null
sleep 0.5
rm -f "$LOG"
touch "$LOG" || { echo "FATAL: cannot write log"; exit 3; }

env -i \
  HOME="$HOME" \
  PATH="$PATH" \
  PREFIX="$PREFIX" \
  LD_LIBRARY_PATH="$LD_LIBRARY_PATH" \
  TMPDIR="$TMPDIR" \
  LANG="$LANG" \
  PYTHONUNBUFFERED=1 \
  PYTHONHOME="$PREFIX" \
  nohup "$PREFIX/bin/python3" "$HOME/mini_console.py" > "$LOG" 2>&1 &

echo "launched pid=$!"
sleep 4

if pgrep -f mini_console.py >/dev/null 2>&1; then
  echo "RUNNING ok"
else
  echo "NOT_RUNNING"
  echo "--- log ---"
  tail -25 "$LOG"
fi
