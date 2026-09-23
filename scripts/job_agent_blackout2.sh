#!/data/data/com.termux/files/usr/bin/bash
# 断线实验 #2b：起跑前用"局域网 keep-alive"顶住系统冻结（替代纯 sleep 空等）
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export AGENT_ENGINE=jev
exec > "$HOME/bridge/out/agent_blackout2.out" 2>&1
echo "TS_JOB_START=$(date +%s)"
i=0
while [ $i -lt 8 ]; do
  python3 -c "import urllib.request;urllib.request.urlopen('http://192.168.3.75:8888/v1/models',timeout=4)" >/dev/null 2>&1 || true
  i=$((i+1)); sleep 1
done
echo "TS_AGENT_START=$(date +%s) (PC link cut long ago)"
python3 /data/local/tmp/mini_agent.py "打开设置应用，找到并告诉我电池电量百分比（数字和充电状态）" --max-steps 12
echo "rc=$?"
echo "TS_END=$(date +%s)"
