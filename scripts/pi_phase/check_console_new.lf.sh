#!/system/bin/sh
# check_console_new.sh — 验证新版控制台（Pi 芯片 + 接口）
P=/data/data/com.termux/files/usr
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

echo "== pids =="
pgrep -U 0 -f "mini_console[.]py"
echo "== main page pi chip =="
curl -s http://127.0.0.1:8900/ | grep -o 'data-m="pi"' | head -2
echo "== chat page pi chip =="
curl -s http://127.0.0.1:8900/chat | grep -o 'm-pi' | head -2
echo "== status =="
curl -s http://127.0.0.1:8900/api/status | head -c 300
echo
echo "== done =="
