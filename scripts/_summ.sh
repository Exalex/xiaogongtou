#!/system/bin/sh
cd /data/data/com.termux/files/home/bridge/runs
for f in $(ls -t *.out | head -5); do
  echo "===== $f ====="
  grep -E "task:|规划骨架|命中脚本|结果复核|骨架断裂|脚本断裂|engine-usage|DONE:" "$f" | head -14
done
