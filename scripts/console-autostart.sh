#!/system/bin/sh
# Magisk service.d 启动器：开机后把控制台守护循环 fork 到后台，本脚本立即退出。
if command -v setsid >/dev/null 2>&1; then
  setsid sh /data/adb/mobilerun-console/supervisor-loop.sh </dev/null >>/data/local/tmp/console_supervisor.log 2>&1 &
else
  sh /data/adb/mobilerun-console/supervisor-loop.sh </dev/null >>/data/local/tmp/console_supervisor.log 2>&1 &
fi
exit 0
