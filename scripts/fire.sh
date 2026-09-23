#!/system/bin/sh
# fire.sh — 固定入口：以 Termux 身份触发 RUN_COMMAND，执行 /data/local/tmp/job.lf.sh
# 由 PC 侧通过 `su 10353 -c 'sh /data/local/tmp/fire.sh'` 调用。
/system/bin/am startservice --user 0 \
  -n com.termux/com.termux.app.RunCommandService \
  -a com.termux.RUN_COMMAND \
  --es com.termux.RUN_COMMAND_PATH /data/data/com.termux/files/usr/bin/bash \
  --esa com.termux.RUN_COMMAND_ARGUMENTS "-c,sh /data/local/tmp/job.lf.sh" \
  --ez com.termux.RUN_COMMAND_BACKGROUND true \
  --es com.termux.RUN_COMMAND_SESSION_ACTION 0
echo "fire_rc=$?"
