#!/data/data/com.termux/files/usr/bin/bash
# job_bashrc_autostart.sh — 给 ~/.bashrc 加"打开 Termux 自动拉起控制台"（幂等）
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
exec > "$HOME/bridge/out/bashrc_autostart.out" 2>&1
if grep -q "mini_console auto-start" "$HOME/.bashrc" 2>/dev/null; then
  echo "already present"
else
  cat >> "$HOME/.bashrc" <<'EOF'

# mini_console auto-start (idempotent): 打开 Termux 时若控制台不在跑就拉起
if ! pgrep -f mini_console.py >/dev/null 2>&1; then
  python3 -c "import subprocess,os; h=os.path.expanduser('~'); l=open(h+'/bridge/out/console.log','ab'); p=subprocess.Popen(['python3',h+'/mini_console.py'],stdout=l,stderr=l,stdin=subprocess.DEVNULL,start_new_session=True)"
fi
EOF
  echo "appended"
fi
echo "--- tail .bashrc ---"
tail -8 "$HOME/.bashrc"
echo "=== done"
