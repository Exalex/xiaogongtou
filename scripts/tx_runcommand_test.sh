#!/system/bin/sh
# 以 Termux 身份（uid 10353）调用 RUN_COMMAND——测试"同 uid 自调用"是否放行
/system/bin/am startservice --user 0 \
  -n com.termux/com.termux.app.RunCommandService \
  -a com.termux.RUN_COMMAND \
  --es com.termux.RUN_COMMAND_PATH /data/data/com.termux/files/usr/bin/bash \
  --esa com.termux.RUN_COMMAND_ARGUMENTS "-c,echo RUNCMD-OK from-termux-uid > /data/data/com.termux/files/home/run_ok.txt" \
  --ez com.termux.RUN_COMMAND_BACKGROUND true \
  --es com.termux.RUN_COMMAND_SESSION_ACTION 0
echo "am_exit=$?"
