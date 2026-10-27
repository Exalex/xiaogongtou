#!/system/bin/sh
# 自录自测脚本：录屏中段自动模拟音量下键（关闭/重开循环），保证动画全程入镜
echo "START $(date +%H:%M:%S.%3N)"
screenrecord --time-limit 13 /data/local/tmp/vt6.mp4 &
RP=$!
sleep 2.5
echo "K1 $(date +%H:%M:%S.%3N)"
sendevent /dev/input/event3 1 114 1
sendevent /dev/input/event3 0 0 0
sleep 0.1
sendevent /dev/input/event3 1 114 0
sendevent /dev/input/event3 0 0 0
sleep 1.8
echo "K2 $(date +%H:%M:%S.%3N)"
sendevent /dev/input/event3 1 114 1
sendevent /dev/input/event3 0 0 0
sleep 0.1
sendevent /dev/input/event3 1 114 0
sendevent /dev/input/event3 0 0 0
sleep 2.0
echo "K3 $(date +%H:%M:%S.%3N)"
sendevent /dev/input/event3 1 114 1
sendevent /dev/input/event3 0 0 0
sleep 0.1
sendevent /dev/input/event3 1 114 0
sendevent /dev/input/event3 0 0 0
sleep 1.6
echo "K4 $(date +%H:%M:%S.%3N)"
sendevent /dev/input/event3 1 114 1
sendevent /dev/input/event3 0 0 0
sleep 0.1
sendevent /dev/input/event3 1 114 0
sendevent /dev/input/event3 0 0 0
wait $RP
echo "END $(date +%H:%M:%S.%3N)"
