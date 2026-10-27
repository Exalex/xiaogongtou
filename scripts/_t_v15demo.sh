#!/system/bin/sh
# v1.5 光效演示录屏：桌面 → 唤起(全动画) → 停留(呼吸) → 停止(进待确认)
echo "START $(date +%H:%M:%S.%3N)"
K1() {
  sendevent /dev/input/event3 1 114 1
  sendevent /dev/input/event3 0 0 0
  sleep 0.1
  sendevent /dev/input/event3 1 114 0
  sendevent /dev/input/event3 0 0 0
}
screenrecord --time-limit 14 /data/local/tmp/v15_demo.mp4 &
RP=$!
sleep 2
K1
sleep 6
K1
sleep 4
wait $RP
echo "END $(date +%H:%M:%S.%3N)"
