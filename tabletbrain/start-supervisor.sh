#!/data/data/com.termux/files/usr/bin/bash
# start-supervisor.sh — 启动/停止自愈守护（每 5 分钟检查 portal + console）
# 用法：  bash ~/start-supervisor.sh          # 启动
#         bash ~/start-supervisor.sh stop     # 停止
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin:/system/xbin
export LD_LIBRARY_PATH=$PREFIX/lib
cd "$HOME" || exit 1
mkdir -p "$HOME/bridge/out"

if [ "$1" = "stop" ]; then
  pkill -f supervisor-loop.sh && echo "自愈已停止" || echo "自愈本来就没在跑"
  exit 0
fi

pkill -f supervisor-loop.sh 2>/dev/null
sleep 0.5
# 用 python 起独立会话进程：adb shell 退出不会连带杀掉
python3 -c "import subprocess,os; h=os.path.expanduser('~'); l=open(h+'/bridge/out/supervisor.log','ab'); p=subprocess.Popen(['bash',h+'/supervisor-loop.sh'],stdout=l,stderr=l,stdin=subprocess.DEVNULL,start_new_session=True); print('supervisor pid', p.pid)"
sleep 3
tail -3 "$HOME/bridge/out/supervisor.log" 2>/dev/null
