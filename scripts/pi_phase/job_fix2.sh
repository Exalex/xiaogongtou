#!/system/bin/sh
# job_fix2.sh — 非交互完成 openssl 配置 + 排查 npm
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

echo "== configure openssl (force confnew) =="
dpkg --force-confnew --configure openssl 2>&1 | tail -5

echo "== versions =="
dpkg-query -W -f='${Package} ${Version} ${Status}\n' openssl zlib libc++ nodejs git 2>&1

echo "== npm check =="
ls -la $PREFIX/bin/ | grep -iE "npm|node|npx"
echo "--- node_modules top ---"
ls $PREFIX/lib/node_modules 2>/dev/null
echo "--- npm --version (full path) ---"
$PREFIX/bin/npm --version 2>&1
echo "== done =="
