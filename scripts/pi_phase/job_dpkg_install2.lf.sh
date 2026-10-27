#!/system/bin/sh
# job_dpkg_install2.sh — 升级 zlib/libc++/openssl（修 node 链接失败）并复测
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

cd $HOME/bridge/pi-debs || { echo "no deb dir"; exit 1; }

echo "== dpkg -i (upgrade) uid=$(id -u) =="
dpkg -i zlib_1.3.2_aarch64.deb libc++_30_aarch64.deb "openssl_1:3.6.3_aarch64.deb" 2>&1 | tail -15

echo "== node test =="
node --version && node -e 'console.log("node_ok", process.arch, process.version)'
npm --version
git --version
echo "== done =="
