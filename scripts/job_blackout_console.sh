#!/data/data/com.termux/files/usr/bin/bash
# 断线实验（控制台版）：手机本机脚本 POST 任务给控制台 → 电脑立即掐线
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
exec > "$HOME/bridge/out/blackout_console.out" 2>&1
echo "TS_JOB_START=$(date +%s)"
python3 "$HOME/console_post.py" "打开设置，找到并告诉我电池电量百分比（数字和充电状态）" auto
echo "rc=$?"
echo "TS_POST_DONE=$(date +%s)"
