#!/system/bin/sh
# deploy_p0.sh — 部署 P0/P1（数据仓 + 对话壳 + 测试/正式模式）到手机控制台
# 前提：store.py / chat_ui.py / mini_console.py / mini_agent.py 已在 /data/local/tmp
H=/data/data/com.termux/files/home
TMP=/data/local/tmp
PY=/data/data/com.termux/files/usr/bin/python3
echo "TS=$(date +%s)"
cp $TMP/store.py $H/store.py
cp $TMP/chat_ui.py $H/chat_ui.py
cp $TMP/mini_console.py $H/mini_console.py
cp $TMP/mini_agent.py $H/mini_agent.py
chown root:root $H/store.py $H/chat_ui.py $H/mini_console.py $H/mini_agent.py
chmod 700 $H/store.py $H/chat_ui.py $H/mini_console.py $H/mini_agent.py
echo "--- files ---"
ls -la $H/store.py $H/chat_ui.py $H/mini_console.py
echo "--- restart console ---"
pkill -f mini_console.py 2>/dev/null
sleep 1
setsid sh /data/adb/mobilerun-console/run.sh </dev/null >>/data/local/tmp/console_supervisor.log 2>&1 &
sleep 3
$PY -c "import urllib.request;r=urllib.request.urlopen('http://127.0.0.1:8900/api/status',timeout=8);print('probe',r.status,r.read().decode()[:200])" || echo "PROBE FAILED"
echo "=== deploy done"
