#!/data/data/com.termux/files/usr/bin/bash
# 流量实验 job：$1 = lan|wan，$2 = 持续秒数（默认 60）
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
KIND="${KIND:-wan}"
DUR="${DUR:-60}"
exec > "$HOME/bridge/out/traffic_${KIND}.out" 2>&1
echo "TS_START=$(date +%s) kind=$KIND dur=$DUR"
python3 /data/local/tmp/traffic_test.py "$KIND" "$DUR"
echo "TS_END=$(date +%s)"
