#!/system/bin/sh
# deploy_console_v2b.sh — 更新 mini_console.py（status engine 字段修复）并重启控制台
P=/data/data/com.termux/files/usr
H=/data/data/com.termux/files/home
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

cp /data/local/tmp/mini_console.py.new $H/mini_console.py
chown 10353:10353 $H/mini_console.py
chmod 644 $H/mini_console.py
$P/bin/python3 -c "import py_compile; py_compile.compile('$H/mini_console.py', doraise=True, cfile='/data/local/tmp/mc2.pyc'); print('compile OK')"

echo "== kill old =="
for pid in $(pgrep -U 0 -f "mini_console[.]py"); do echo "kill $pid"; kill -9 $pid; done
sleep 2

echo "== start new =="
setsid sh /data/adb/mobilerun-console/run.sh </dev/null >>/data/local/tmp/console_supervisor.log 2>&1 &
sleep 4
echo "== pid =="
pgrep -U 0 -f "mini_console[.]py"
echo "== status =="
curl -s http://127.0.0.1:8900/api/status | head -c 200
echo
echo "== done =="
