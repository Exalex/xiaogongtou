#!/system/bin/sh
# v1.5 流式语音测试：唤起(音量▾) → 流式识别截图 → 再按(停止) → 待确认截图
echo "START $(date +%H:%M:%S.%3N)"
K1() {
  sendevent /dev/input/event3 1 114 1
  sendevent /dev/input/event3 0 0 0
  sleep 0.1
  sendevent /dev/input/event3 1 114 0
  sendevent /dev/input/event3 0 0 0
}
echo "K1(唤起) $(date +%H:%M:%S.%3N)"
K1
sleep 5
screencap -p /data/local/tmp/v15_a.png
echo "shot-a $(date +%H:%M:%S.%3N)"
sleep 3
screencap -p /data/local/tmp/v15_b.png
echo "shot-b $(date +%H:%M:%S.%3N)"
echo "K2(停止) $(date +%H:%M:%S.%3N)"
K1
sleep 5
screencap -p /data/local/tmp/v15_c.png
echo "shot-c $(date +%H:%M:%S.%3N)"
echo "END $(date +%H:%M:%S.%3N)"
