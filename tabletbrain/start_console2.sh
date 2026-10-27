#!/data/data/com.termux/files/usr/bin/bash
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin:/system/xbin
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp
export LANG=en_US.UTF-8

cd "$HOME" || exit 1
mkdir -p "$HOME/bridge/out" "$HOME/bridge/runs" "$HOME/bridge/skills" "$HOME/bridge/examples"

pkill -f mini_console.py 2>/dev/null
sleep 0.5

nohup "$PREFIX/bin/python3" "$HOME/mini_console.py" > "$HOME/bridge/out/console.log" 2>&1 &
echo "launched pid=$!"
sleep 3

if ps -A 2>/dev/null | grep -q mini_console; then
  echo "RUNNING"
else
  echo "NOT_RUNNING - log tail:"
  tail -20 "$HOME/bridge/out/console.log"
fi
