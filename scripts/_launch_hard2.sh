#!/system/bin/sh
H=/data/data/com.termux/files/home
PY=/data/data/com.termux/files/usr/bin/python3
OUT=/data/local/tmp/rhard2.txt
rm -f $OUT
cd $H
export TASKS="打开开盘啦，看今天跌停家数,打开B站，搜索罗翔，看第一个视频的播放量,打开今日头条，看热榜前三条是什么,打开淘宝，搜索蓝牙耳机，看第一个商品多少钱,打开微博，看热搜前五是什么"
HOME=$H setsid $PY -u $H/_run_random.py 5 165 </dev/null >>$OUT 2>&1 &
echo "started pid=$!"
