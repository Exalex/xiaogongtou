#!/system/bin/sh
# deploy_fix_round.sh — 部署 wx_intent/mini_agent/mini_console 修复并重启控制台
P=/data/data/com.termux/files/usr
H=/data/data/com.termux/files/home
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib
TU=10353

for f in wx_intent.py mini_agent.py mini_console.py; do
  cp /data/local/tmp/$f.new $H/$f
  chown $TU:$TU $H/$f
  chmod 644 $H/$f
done
$P/bin/python3 -c "import py_compile;[py_compile.compile('$H/'+f, doraise=True, cfile='/data/local/tmp/x.pyc') for f in ['wx_intent.py','mini_agent.py','mini_console.py']]; print('compile OK')"

echo "== wx_intent self-test (phone) =="
cd $H && $P/bin/python3 wx_intent.py 2>&1 | tail -8

echo "== restart console =="
for pid in $(pgrep -U 0 -f "mini_console[.]py"); do echo "kill $pid"; kill -9 $pid; done
sleep 2
setsid sh /data/adb/mobilerun-console/run.sh </dev/null >>/data/local/tmp/console_supervisor.log 2>&1 &
sleep 4
echo "== pid =="
pgrep -U 0 -f "mini_console[.]py"
echo "== status =="
curl -s http://127.0.0.1:8900/api/status | head -c 150
echo
echo "== done =="
