#!/system/bin/sh
# mobilerun console runner（以 root 运行；使用 Termux 的 Python 环境）
export TERMUX_PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$TERMUX_PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$TERMUX_PREFIX/lib
export LANG=en_US.UTF-8
cd $HOME
exec $TERMUX_PREFIX/bin/python3 $HOME/mini_console.py
