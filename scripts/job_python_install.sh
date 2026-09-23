export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export LD_LIBRARY_PATH=$PREFIX/lib
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
export LANG=en_US.UTF-8
exec > "$HOME/bridge/out/python_install.out" 2>&1

echo "=== start: $(date) ==="
echo "--- sources.list ---"
cat "$PREFIX/etc/apt/sources.list"
echo "--- connectivity (termux identity) ---"
ping -c 2 -W 3 mirrors.tuna.tsinghua.edu.cn 2>&1 | tail -3
echo "--- apt update ---"
apt update
echo "update_rc=$?"
echo "--- install python ---"
DEBIAN_FRONTEND=noninteractive apt install -y python
echo "install_rc=$?"
echo "--- verify ---"
python3 --version
pip3 --version
echo "final_rc=$?"
echo "=== done: $(date) ==="
