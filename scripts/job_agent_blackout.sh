#!/data/data/com.termux/files/usr/bin/bash
# 断线实验 #2：任务延迟 8 秒起跑，确保整个 agent 运行期 PC 连接都是断开的
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export AGENT_ENGINE=jev
exec > "$HOME/bridge/out/agent_blackout.out" 2>&1
echo "TS_JOB_START=$(date +%s)"
sleep 8
echo "TS_AGENT_START=$(date +%s) (PC link should be CUT by now)"
python3 /data/local/tmp/mini_agent.py "打开设置应用，找到并告诉我电池电量百分比（数字和充电状态）" --max-steps 12
echo "rc=$?"
echo "TS_END=$(date +%s)"
