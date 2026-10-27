#!/system/bin/sh
# tx_install_node.sh — 以 root 身份在 Termux 环境安装 nodejs + git（P0）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

echo "===== sources.list ====="
head -5 $PREFIX/etc/apt/sources.list 2>/dev/null

echo "===== apt update ====="
apt update 2>&1 | tail -6

echo "===== apt install nodejs git ====="
DEBIAN_FRONTEND=noninteractive apt install -y nodejs git 2>&1 | tail -25

echo "===== verify ====="
node --version 2>&1
npm --version 2>&1
git --version 2>&1

echo "===== fix dpkg/apt ownership back to termux user ====="
TU=$(stat -c %u /data/data/com.termux/files/home 2>/dev/null)
echo "termux uid=$TU"
[ -n "$TU" ] && chown -R $TU:$TU $PREFIX/var/lib/dpkg $PREFIX/var/cache/apt 2>/dev/null
echo "===== node install done ====="
