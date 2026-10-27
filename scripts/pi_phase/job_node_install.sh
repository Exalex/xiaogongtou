#!/data/data/com.termux/files/usr/bin/bash
# job.lf.sh — 以 Termux app 身份安装 nodejs + git（网络/DNS 走 app 上下文）
# 输出落 $HOME/bridge/out/node_install.out（PC 侧 root 读取）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

mkdir -p $HOME/bridge/out
OUT=$HOME/bridge/out/node_install.out
exec > $OUT 2>&1

echo "=== start $(date '+%F %T') uid=$(id -u) ==="
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock && echo "wake-lock on"

echo "=== apt update ==="
apt update 2>&1 | tail -8

echo "=== apt install nodejs git ==="
DEBIAN_FRONTEND=noninteractive apt install -y nodejs git 2>&1 | tail -30

echo "=== verify ==="
node --version 2>&1 || echo "node missing"
npm --version 2>&1 || echo "npm missing"
git --version 2>&1 || echo "git missing"

command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock
echo "=== done $(date '+%F %T') rc_chain=$? ==="
