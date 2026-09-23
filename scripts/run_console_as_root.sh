#!/system/bin/sh
# 以 root 身份运行 mini_console（使用 Termux 的 Python 与文件系统环境）
# 目的：root 进程不受 ColorOS 应用冻结影响 → 控制台永远在线
export TERMUX_PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$TERMUX_PREFIX/bin:$PATH
export LD_LIBRARY_PATH=$TERMUX_PREFIX/lib
export LANG=en_US.UTF-8
cd $HOME
exec $TERMUX_PREFIX/bin/python3 $HOME/mini_console.py
