#!/data/data/com.termux/files/usr/bin/bash
# start-console.sh — 手机端：启动/停止本机控制台（在 Termux 里跑）
# 用法：  bash ~/start-console.sh          # 启动（重启式）
#         bash ~/start-console.sh stop     # 停止
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
cd "$HOME" || exit 1

if [ "$1" = "stop" ]; then
  pkill -f mini_console.py && echo "控制台已停止" || echo "控制台本来就没在跑"
  exit 0
fi

pkill -f mini_console.py 2>/dev/null
sleep 0.5
mkdir -p "$HOME/bridge/out" "$HOME/bridge/runs"
python3 -c "import subprocess,os; h=os.path.expanduser('~'); l=open(h+'/bridge/out/console.log','ab'); p=subprocess.Popen(['python3',h+'/mini_console.py'],stdout=l,stderr=l,stdin=subprocess.DEVNULL,start_new_session=True); print('console pid', p.pid)"
sleep 1.2
python3 -c "import urllib.request; print('self-check:', urllib.request.urlopen('http://127.0.0.1:8900/api/status',timeout=5).status)" || echo "启动失败：请看 ~/bridge/out/console.log"
echo ""
echo "在手机浏览器打开： http://127.0.0.1:8900/"
