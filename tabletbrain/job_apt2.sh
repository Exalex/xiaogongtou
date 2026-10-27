#!/data/data/com.termux/files/usr/bin/bash
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp
mkdir -p "$TMPDIR" "$HOME/bridge/out"

exec > "$HOME/bridge/out/apt2.out" 2>&1
echo "=== START $(date) uid=$(id -u) ==="
echo "--- apt update ---"
apt-get update -y 2>&1 | tail -10
echo "--- install python ---"
DEBIAN_FRONTEND=noninteractive apt-get install -y python 2>&1 | tail -25
echo "--- verify ---"
ls -la $PREFIX/bin/ | grep -E "python|pip" | head -5
$PREFIX/bin/python -V 2>&1
echo "=== DONE $(date) ==="
