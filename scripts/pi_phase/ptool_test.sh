#!/system/bin/sh
# ptool_test.sh — ptool 只读子命令自检（root）
PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp

echo "== battery =="
python3 $HOME/bridge/tools/ptool.py battery
echo "== front =="
python3 $HOME/bridge/tools/ptool.py front | tail -6
echo "== apps count =="
python3 $HOME/bridge/tools/ptool.py apps | head -3
echo "== done =="
