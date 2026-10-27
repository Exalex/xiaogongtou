#!/system/bin/sh
H=/data/data/com.termux/files/home
PY=/data/data/com.termux/files/usr/bin/python3
OUT=/data/local/tmp/probe5.txt
rm -f $OUT
cd $H
HOME=$H setsid $PY -u $H/_probe5.py </dev/null >>$OUT 2>&1 &
echo "started pid=$!"
