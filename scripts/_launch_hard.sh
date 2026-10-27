#!/system/bin/sh
H=/data/data/com.termux/files/home
PY=/data/data/com.termux/files/usr/bin/python3
OUT=/data/local/tmp/rhard.txt
rm -f $OUT
cd $H
export TASKS="打开B站，看热门榜前三个视频是什么,打开今日头条，看热榜前三条是什么,打开微博，看热搜前五是什么"
HOME=$H setsid $PY -u $H/_run_random.py 3 150 </dev/null >>$OUT 2>&1 &
echo "started pid=$!"
