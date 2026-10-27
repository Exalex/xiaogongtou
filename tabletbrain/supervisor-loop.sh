#!/data/data/com.termux/files/usr/bin/bash
# supervisor-loop.sh (tablet v1) — 每 5 分钟自检 portal + console，异常自愈
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin:/system/xbin
export LD_LIBRARY_PATH=$PREFIX/lib

PORTAL_SVC="com.mobilerun.portal/com.mobilerun.portal.service.MobilerunAccessibilityService"
ENTRY_SVC="com.xiaogongtou.entry/com.xiaogongtou.entry.EntryA11yService"
LOG="$HOME/bridge/out/supervisor.log"
mkdir -p "$HOME/bridge/out"

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }

probe() {
  # $1 = url
  "$PREFIX/bin/python3" - "$1" <<'PY' 2>/dev/null
import sys, urllib.request
try:
    r = urllib.request.urlopen(sys.argv[1], timeout=6)
    sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

check_portal() {
  if ! pidof com.mobilerun.portal >/dev/null 2>&1; then
    log "portal: process gone -> relaunch"
    monkey -p com.mobilerun.portal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    sleep 8
  fi
  if ! probe "http://127.0.0.1:8080/ping"; then
    log "portal: 8080 down -> re-enable a11y + toggle socket"
    settings put secure accessibility_enabled 0
    settings put secure enabled_accessibility_services ''
    sleep 1
    settings put secure enabled_accessibility_services "$PORTAL_SVC:$ENTRY_SVC"
    settings put secure accessibility_enabled 1
    sleep 4
    kill -9 "$(pidof com.mobilerun.portal)" 2>/dev/null
    sleep 2
    monkey -p com.mobilerun.portal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    sleep 8
    content insert --uri content://com.mobilerun.portal/toggle_socket_server --bind enabled:b:true >/dev/null 2>&1
    sleep 3
    if probe "http://127.0.0.1:8080/ping"; then log "portal: repaired OK"; else log "portal: repair FAILED"; fi
  fi
}

check_console() {
  if ! probe "http://127.0.0.1:8900/api/status"; then
    log "console: 8900 down -> restart"
    pkill -f mini_console.py 2>/dev/null
    sleep 1
    cd "$HOME" || return
    setsid "$PREFIX/bin/python3" "$HOME/mini_console.py" >> "$HOME/bridge/out/console.log" 2>&1 < /dev/null &
    sleep 4
    if probe "http://127.0.0.1:8900/api/status"; then log "console: restarted OK"; else log "console: restart FAILED"; fi
  fi
}

log "=== supervisor start (pid $$) ==="
while true; do
  check_portal
  check_console
  sleep 300
done
