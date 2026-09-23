#!/data/data/com.termux/files/usr/bin/bash
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$PREFIX/lib
exec > "$HOME/bridge/out/probe.out" 2>&1
echo "=== start $(date) ==="
python3 /data/local/tmp/probe.py
echo "rc=$?"
echo "=== done $(date) ==="
