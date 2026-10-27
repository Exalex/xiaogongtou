#!/system/bin/sh
# 手动触发 portal「修复三部曲」（守护脚本的 portal 检查只看"进程+端口在听"，
# 检测不到"端口在听但不收连接"的假活状态 —— 2026-10-11 实证）。
PORTAL_SVC=com.mobilerun.portal/com.mobilerun.portal.service.MobilerunAccessibilityService
ENTRY_SVC=com.xiaogongtou.entry/com.xiaogongtou.entry.EntryA11yService
PY=/data/data/com.termux/files/usr/bin/python3
H=/data/data/com.termux/files/home

echo "=== 修复前探测 ==="
HOME=$H $PY $H/_probe_portal.py 2>/dev/null || echo "(无探测脚本，跳过)"

echo "=== 1) 清空重设 a11y ==="
settings put secure accessibility_enabled 0
settings put secure enabled_accessibility_services ""
sleep 1
settings put secure enabled_accessibility_services "$PORTAL_SVC:$ENTRY_SVC"
settings put secure accessibility_enabled 1
sleep 6

echo "=== 2) portal 进程 ==="
if ! pidof com.mobilerun.portal >/dev/null 2>&1; then
  echo "  portal 不在 → monkey 拉起"
  monkey -p com.mobilerun.portal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep 5
fi
echo "  portal pid=$(pidof com.mobilerun.portal)"

echo "=== 3) toggle socket server ==="
content insert --uri content://com.mobilerun.portal/toggle_socket_server --bind enabled:b:true 2>&1 | head -2
sleep 3

echo "=== 修复后：真实 HTTP 探测 ==="
HOME=$H $PY -c "
import urllib.request, json, os
tok = ''
try:
    tok = (json.load(open(os.path.expanduser('~/bridge/secrets.json'))) or {}).get('portal_token','')
except Exception:
    pass
for path in ('/ping','/version'):
    try:
        req = urllib.request.Request('http://127.0.0.1:8080'+path)
        if tok: req.add_header('Authorization','Bearer '+tok)
        r = urllib.request.urlopen(req, timeout=8)
        print('  %-9s OK %d %s' % (path, r.status, r.read()[:80]))
    except Exception as e:
        print('  %-9s FAIL %r' % (path, e))
"
echo "=== done ==="
