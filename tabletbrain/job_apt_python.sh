#!/data/data/com.termux/files/usr/bin/bash
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin:/system/xbin
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp
mkdir -p "$TMPDIR" "$HOME/bridge/out"

exec > "$HOME/bridge/out/apt_install.out" 2>&1
echo "=== START $(date) ==="
echo "--- apt update ---"
apt-get update -y 2>&1 | tail -8
echo "--- apt install python ---"
DEBIAN_FRONTEND=noninteractive apt-get install -y python python-pip 2>&1 | tail -20
echo "--- verify ---"
which python python3 pip 2>&1
python -V 2>&1
echo "=== DONE $(date) ==="
