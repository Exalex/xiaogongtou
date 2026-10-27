#!/data/data/com.termux/files/usr/bin/bash
# job.lf.sh (trivial fire channel test)
HOME=/data/data/com.termux/files/home
mkdir -p $HOME/bridge/out
echo "fire_ok $(date +%s) uid=$(id -u)" > $HOME/bridge/out/fire_test.out
