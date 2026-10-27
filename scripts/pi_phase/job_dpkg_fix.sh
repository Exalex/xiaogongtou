#!/system/bin/sh
# job_dpkg_fix.sh — 清理中断残留 + 升级 zlib/libc++/openssl + 复测 node（输出落文件）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

mkdir -p $HOME/bridge/out
OUT=$HOME/bridge/out/dpkg_fix.out
exec > $OUT 2>&1

echo "=== start $(date +%T) uid=$(id -u) ==="
if pgrep -x dpkg >/dev/null 2>&1; then
  echo "!! dpkg still running, abort"
  exit 9
fi
echo "--- clean stale locks ---"
rm -f $PREFIX/var/lib/dpkg/lock $PREFIX/var/lib/dpkg/lock-frontend
echo "--- dpkg --configure -a ---"
dpkg --configure -a 2>&1 | tail -5

cd $HOME/bridge/pi-debs || { echo "no debs"; exit 1; }
echo "--- dpkg -i upgrade ---"
dpkg -i zlib_1.3.2_aarch64.deb libc++_30_aarch64.deb "openssl_1:3.6.3_aarch64.deb" 2>&1 | tail -20

echo "--- versions ---"
dpkg-query -W -f='${Package} ${Version} ${Status}\n' zlib libc++ openssl nodejs git 2>&1

echo "--- node test ---"
node --version && node -e 'console.log("node_ok", process.arch, process.version)'
npm --version
git --version
echo "=== done $(date +%T) ==="
