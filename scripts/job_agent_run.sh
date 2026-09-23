#!/data/data/com.termux/files/usr/bin/bash
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
exec > "$HOME/bridge/out/agent.out" 2>&1
echo "=== agent start $(date) ==="
python3 /data/local/tmp/check_llm.py
echo "---"
TASK="打开设置应用，找到并告诉我电池电量百分比（数字和充电状态）"
python3 /data/local/tmp/mini_agent.py "$TASK" --max-steps 15
echo "rc=$?"
echo "=== agent end $(date) ==="
