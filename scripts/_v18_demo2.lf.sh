#!/system/bin/sh
# v1.8 冰蓝配色演示：录屏 14s + 1.2s 后触发语音条
screenrecord --time-limit 14 /data/local/tmp/v18_ice.mp4 &
sleep 1.2
sendevent /dev/input/event3 1 114 1
sendevent /dev/input/event3 0 0 0
sleep 0.08
sendevent /dev/input/event3 1 114 0
sendevent /dev/input/event3 0 0 0
wait
echo REC_DONE
