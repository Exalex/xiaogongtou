#!/system/bin/sh
# 守护循环（root 常驻）:
#   1) 每分钟检查 mini_console.py（root 进程）是否存活，离线则拉起；
#   2) 每 5 分钟检查 portal（手和眼）:进程 + 8080 监听；异常则执行"修复三部曲"
#      (清空重设 a11y → 必要时 monkey 拉起 → toggle socket server)；
#   3) 每 5 分钟检查「小工头」入口 App 的 a11y 服务是否在启用列表里，
#      被系统清掉则补回（ColorOS 会清理 sideload 应用的 a11y 服务）。
# 由 Magisk service.d 在开机时启动（console-autostart.sh），也可手动执行。
until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 5; done
sleep 15
LOG=/data/local/tmp/console_supervisor.log
RUN=/data/adb/mobilerun-console/run.sh
PORTAL_SVC=com.mobilerun.portal/com.mobilerun.portal.service.MobilerunAccessibilityService
ENTRY_SVC=com.xiaogongtou.entry/com.xiaogongtou.entry.EntryA11yService
echo "[$(date)] supervisor started" >> $LOG
i=0
while true; do
  # ---- console 守护 ----
  if ! pgrep -U 0 -f "mini_console.py" >/dev/null 2>&1; then
    echo "[$(date)] console down -> starting as root" >> $LOG
    if command -v setsid >/dev/null 2>&1; then
      setsid sh $RUN </dev/null >>$LOG 2>&1 &
    else
      sh $RUN </dev/null >>$LOG 2>&1 &
    fi
    sleep 6
  fi
  # ---- xgt-bridge（root 桥：树导出 + input 容灾）守护 ----
  if ! pgrep -f "xgt[-]bridge.sh" >/dev/null 2>&1; then
    echo "[$(date)] xgt-bridge down -> restarting" >> $LOG
    if command -v setsid >/dev/null 2>&1; then
      setsid sh /data/adb/mobilerun-console/xgt-bridge.sh </dev/null >/dev/null 2>&1 &
    else
      sh /data/adb/mobilerun-console/xgt-bridge.sh </dev/null >/dev/null 2>&1 &
    fi
    sleep 2
  fi
  # ---- 每 5 轮（≈5 分钟）检查 ----
  i=$((i+1))
  if [ $((i % 5)) -eq 0 ]; then
    # 4) 入口 App 进程看护：进程死了（系统清理/o-stop）→ 靠 a11y 服务 toggle 拉起
    #    （a11y 服务在启用列表里 ≠ 进程活着；桥树/浮球/通知都依赖该进程）
    if ! pidof com.xiaogongtou.entry >/dev/null 2>&1; then
      echo "[$(date)] entry app process down -> a11y toggle to revive" >> $LOG
      CUR2=$(settings get secure enabled_accessibility_services)
      settings put secure enabled_accessibility_services "$PORTAL_SVC"
      sleep 1
      settings put secure enabled_accessibility_services "$CUR2"
      settings put secure accessibility_enabled 1
      sleep 4
      echo "[$(date)] entry revive done (pid=$(pidof com.xiaogongtou.entry))" >> $LOG
    fi
    # 3) 入口 App 的 a11y 服务补回
    ENTRY_OK=$(settings get secure enabled_accessibility_services | grep -c "xiaogongtou")
    if [ "$ENTRY_OK" = "0" ]; then
      CUR=$(settings get secure enabled_accessibility_services)
      if [ -n "$CUR" ] && [ "$CUR" != "null" ]; then
        NEW="$CUR:$ENTRY_SVC"
      else
        NEW="$ENTRY_SVC"
      fi
      settings put secure enabled_accessibility_services "$NEW"
      settings put secure accessibility_enabled 1
      echo "[$(date)] entry a11y re-added -> $NEW" >> $LOG
    fi
    # 2) portal 守护（注意：重设时两个服务都要写回）
    if ! pidof com.mobilerun.portal >/dev/null 2>&1 || ! grep -q 1F90 /proc/net/tcp6 2>/dev/null; then
      echo "[$(date)] portal check failed -> rebind attempt" >> $LOG
      settings put secure accessibility_enabled 0
      settings put secure enabled_accessibility_services ""
      sleep 1
      settings put secure enabled_accessibility_services "$PORTAL_SVC:$ENTRY_SVC"
      settings put secure accessibility_enabled 1
      sleep 6
      if ! pidof com.mobilerun.portal >/dev/null 2>&1; then
        echo "[$(date)] portal still down -> monkey wake (brief)" >> $LOG
        monkey -p com.mobilerun.portal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
        sleep 4
      fi
      if pidof com.mobilerun.portal >/dev/null 2>&1; then
        content insert --uri content://com.mobilerun.portal/toggle_socket_server --bind enabled:b:true >>$LOG 2>&1
      fi
      echo "[$(date)] portal fix attempt done (pid=$(pidof com.mobilerun.portal)) sock=$(grep -c 1F90 /proc/net/tcp6 2>/dev/null)" >> $LOG
    fi
  fi
  sleep 54
done
