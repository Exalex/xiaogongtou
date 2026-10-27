#!/system/bin/sh
# job_dpkg_install.sh — 以 Termux 用户安装本地 deb（无网络需求，不依赖 DNS）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

cd $HOME/bridge/pi-debs || { echo "no deb dir"; exit 1; }

echo "== dpkg -i (uid=$(id -u)) =="
dpkg -i c-ares_1.34.8_aarch64.deb libicu_78.3_aarch64.deb nodejs_26.4.0-1_aarch64.deb git_2.56.0_aarch64.deb 2>&1 | tail -25

echo "== verify =="
command -v node && node --version
command -v npm && npm --version
command -v git && git --version
echo "== done =="
