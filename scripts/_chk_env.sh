#!/system/bin/sh
H=/data/data/com.termux/files/home
PY=/data/data/com.termux/files/usr/bin/python3
echo "=== run.sh ==="
cat /data/adb/mobilerun-console/run.sh 2>&1
echo "=== console 进程环境（HOME/TERMUX）==="
PID=$(pgrep -U 0 -f mini_console.py | head -1)
echo "console pid=$PID"
if [ -n "$PID" ]; then
  tr '\0' '\n' < /proc/$PID/environ 2>/dev/null | grep -E '^(HOME|PATH|TERMUX_PREFIX|LD_LIBRARY_PATH)=' | head -8
fi
echo "=== agent 侧 HOME 实测（用 run.sh 同款 env）==="
HOME=$H TERMUX_PREFIX=/data/data/com.termux/files/usr \
PATH=$H/../usr/bin:$PATH $PY -c "
import os,sys
sys.path.insert(0, os.environ['HOME'])
print('expanduser ~ =', os.path.expanduser('~'))
import scripts_lib as S
print('scripts =', [s['id'] for s in S.load_scripts()])
c=S.cards_of({})
print('weibo pages =', [p['name'] for p in (c.get('com.sina.weibo') or {}).get('pages') or []])
print('guards =', [g['id'] for g in S.load_guards()])
"
