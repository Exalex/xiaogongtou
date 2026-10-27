#!/system/bin/sh
# job_finish_p0.sh — 安装 npm + 解包 pi 运行时到 ~/pi-runtime（Termux 用户身份）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp

echo "== install npm =="
cd $HOME/bridge/pi-debs || exit 1
dpkg -i npm_11.20.0_all.deb 2>&1 | tail -6

echo "== extract pi runtime =="
mkdir -p $HOME/pi-runtime
cd $HOME/pi-runtime || exit 1
if [ -f node_modules/@earendil-works/pi-coding-agent/dist/cli.js ]; then
  echo "(already extracted)"
else
  if /system/bin/tar xzf /data/local/tmp/pi-runtime-0.82.1.tgz 2>/tmp/pi_tar.log; then
    echo "tar(toybox) ok"
  else
    echo "toybox tar failed ($(cat /tmp/pi_tar.log 2>/dev/null | head -2)) -> python tarfile"
    python3 - <<'PYEOF'
import tarfile
t = tarfile.open('/data/local/tmp/pi-runtime-0.82.1.tgz')
t.extractall('/data/data/com.termux/files/home/pi-runtime')
print('python extract ok, entries:', len(t.getnames()))
PYEOF
  fi
fi
echo "--- top of pi-runtime ---"
ls $HOME/pi-runtime/ | head
echo "--- cli.js ---"
ls -la $HOME/pi-runtime/node_modules/@earendil-works/pi-coding-agent/dist/cli.js 2>&1

echo "== node/npm verify =="
node --version
npm --version 2>&1 | tail -1
echo "== done =="
