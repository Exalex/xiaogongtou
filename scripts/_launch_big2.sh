#!/system/bin/sh
H=/data/data/com.termux/files/home
PY=/data/data/com.termux/files/usr/bin/python3
OUT=/data/local/tmp/pbig2.txt
rm -f $OUT
cd $H
HOME=$H setsid $PY -u $H/_probe_big2.py </dev/null >>$OUT 2>&1 &
echo "started pid=$!"
