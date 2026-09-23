#!/data/data/com.termux/files/usr/bin/sh
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export LD_LIBRARY_PATH=$PREFIX/lib
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
export LANG=en_US.UTF-8

echo "=== [1/3] apt update (TUNA mirror) ==="
apt update 2>&1 | tail -12
echo "rc=$?"

echo "=== [2/3] install python (this may take a few minutes) ==="
DEBIAN_FRONTEND=noninteractive pkg install -y python 2>&1 | tail -30
echo "rc=$?"

echo "=== [3/3] verify ==="
python3 --version 2>&1
python3 -c "import sys; print('exe:', sys.executable)" 2>&1
pip3 --version 2>&1 || echo "pip3 MISSING"
echo "=== DONE ==="
