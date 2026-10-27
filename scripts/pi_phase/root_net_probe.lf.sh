#!/system/bin/sh
# root_net_probe.sh - 探测 root 身份 + Termux env 下的网络/DNS 能力
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

echo "uid=$(id -u)"
echo "--- dns+http test (tuna mirror) ---"
curl -sS --max-time 15 -o /dev/null -w "http=%{http_code} time=%{time_total}s\n" \
  https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main/dists/stable/Release || echo "curl_failed"
echo "--- dns test (npmmirror) ---"
curl -sS --max-time 15 -o /dev/null -w "http=%{http_code} time=%{time_total}s\n" \
  https://registry.npmmirror.com/@earendil-works/pi-coding-agent || echo "curl_failed"
echo "--- apt present? ---"
which apt dpkg node npm 2>&1
