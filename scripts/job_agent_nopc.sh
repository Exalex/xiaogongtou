#!/data/data/com.termux/files/usr/bin/bash
# 断线实验：任务启动后 PC 立即 kill-server，验证 agent 循环不依赖 PC
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export AGENT_ENGINE=jev
exec > "$HOME/bridge/out/agent_nopc.out" 2>&1
echo "TS_START=$(date +%s)"
python3 /data/local/tmp/mini_agent.py "打开设置应用，找到并告诉我电池电量百分比（数字和充电状态）" --max-steps 12
echo "rc=$?"
echo "TS_END=$(date +%s)"
