#!/system/bin/sh
# deploy_p2c.sh — 更新 ptool（影子屏分支）+ mini_console（会话语义）并重启
P=/data/data/com.termux/files/usr
H=/data/data/com.termux/files/home
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

cp /data/local/tmp/ptool.py.new $H/bridge/tools/ptool.py
chown 10353:10353 $H/bridge/tools/ptool.py
chmod 755 $H/bridge/tools/ptool.py
$P/bin/python3 -c "import py_compile; py_compile.compile('$H/bridge/tools/ptool.py', doraise=True, cfile='/data/local/tmp/pt1.pyc'); print('ptool compile OK')"

cp /data/local/tmp/mini_console.py.new $H/mini_console.py
chown 10353:10353 $H/mini_console.py
chmod 644 $H/mini_console.py
$P/bin/python3 -c "import py_compile; py_compile.compile('$H/mini_console.py', doraise=True, cfile='/data/local/tmp/mc3.pyc'); print('console compile OK')"

echo "== restart console =="
for pid in $(pgrep -U 0 -f "mini_console[.]py"); do echo "kill $pid"; kill -9 $pid; done
sleep 2
setsid sh /data/adb/mobilerun-console/run.sh </dev/null >>/data/local/tmp/console_supervisor.log 2>&1 &
sleep 4
echo "== pid =="
pgrep -U 0 -f "mini_console[.]py"
echo "== status =="
curl -s http://127.0.0.1:8900/api/status | head -c 180
echo
echo "== ptool self-check =="
python3 $H/bridge/tools/ptool.py battery | head -3
python3 $H/bridge/tools/ptool.py front | head -2
echo "== done =="
