#!/system/bin/sh
export TERMUX_PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$TERMUX_PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$TERMUX_PREFIX/lib
export LANG=en_US.UTF-8
cd $HOME
$TERMUX_PREFIX/bin/python3 /data/local/tmp/_shadow_open_test.py
