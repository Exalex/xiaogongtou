#!/system/bin/sh
# final_state.sh — 收尾核对（回桌面 + 关键进程 + 无障碍绑定）
P=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

/system/bin/input keyevent 3
sleep 1
echo "== procs =="
echo "console: $(pgrep -U 0 -f 'mini_console[.]py' | head -1)"
echo "entry: $(pgrep -f com.xiaogongtou.entry | head -1)"
echo "shadow: $(pgrep -f shadow_client | head -1)"
echo "bridge: $(pgrep -f 'xgt[-]bridge' | head -1)"
echo "== a11y =="
settings get secure enabled_accessibility_services
echo "== portal probe (ptool front) =="
python3 $HOME/bridge/tools/ptool.py front | head -2
echo "== done =="
