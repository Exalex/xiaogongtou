#!/system/bin/sh
# test_wx_cleanstop.sh — 补跑：wx-send 干净停路径（目标不存在 → 0 点击 0 输入）
P=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$P/bin:$PATH
export LD_LIBRARY_PATH=$P/lib

echo "== clean-stop probe $(date +%T) =="
python3 $HOME/bridge/tools/ptool.py wx-send --to "不存在的目标XYZ测试" --text "test" 2>&1 | tail -8
echo "A_rc=$?"
echo "== done $(date +%T) =="
