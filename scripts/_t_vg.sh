#!/system/bin/sh
# 光效诊断：唤起 → 连拍 4 张（每 1.2s） → 停止（不提交）
echo "START $(date +%H:%M:%S.%3N)"
K1() {
  sendevent /dev/input/event3 1 114 1
  sendevent /dev/input/event3 0 0 0
  sleep 0.1
  sendevent /dev/input/event3 1 114 0
  sendevent /dev/input/event3 0 0 0
}
K1
sleep 0.8
screencap -p /data/local/tmp/vg_1.png
sleep 1.0
screencap -p /data/local/tmp/vg_2.png
sleep 1.2
screencap -p /data/local/tmp/vg_3.png
sleep 1.2
screencap -p /data/local/tmp/vg_4.png
echo "shots done $(date +%H:%M:%S.%3N)"
K1
sleep 1
echo "END $(date +%H:%M:%S.%3N)"
