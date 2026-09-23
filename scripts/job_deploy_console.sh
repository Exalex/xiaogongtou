#!/data/data/com.termux/files/usr/bin/bash
# job_deploy_console.sh — 部署/更新手机本机控制台（源文件已在 /data/local/tmp）
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
exec > "$HOME/bridge/out/deploy_console.out" 2>&1
echo "TS=$(date +%s)"
mkdir -p "$HOME/bridge/out" "$HOME/bridge/runs"
cp /data/local/tmp/mini_agent.py "$HOME/mini_agent.py"
cp /data/local/tmp/mini_console.py "$HOME/mini_console.py"
cp /data/local/tmp/console_post.py "$HOME/console_post.py"
cp /data/local/tmp/start-console.sh "$HOME/start-console.sh"
chmod 700 "$HOME/mini_agent.py" "$HOME/mini_console.py" "$HOME/console_post.py" "$HOME/start-console.sh"
echo "--- files ---"
ls -la "$HOME/mini_agent.py" "$HOME/mini_console.py" "$HOME/start-console.sh" "$HOME/console_post.py"
echo "--- restart console ---"
pkill -f mini_console.py 2>/dev/null
sleep 0.5
python3 -c "import subprocess,os; h=os.path.expanduser('~'); l=open(h+'/bridge/out/console.log','ab'); p=subprocess.Popen(['python3',h+'/mini_console.py'],stdout=l,stderr=l,stdin=subprocess.DEVNULL,start_new_session=True); print('console pid', p.pid)"
sleep 1.5
python3 -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8900/api/status',timeout=6); print('probe', r.status, r.read().decode()[:220])" || echo "PROBE FAILED"
echo "=== deployed"
