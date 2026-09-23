export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export LD_LIBRARY_PATH=$PREFIX/lib
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
export LANG=en_US.UTF-8
exec > "$HOME/bridge/out/pip_check.out" 2>&1

echo "=== start: $(date) ==="
echo "--- set pip mirror (TUNA) ---"
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
echo "--- install httpx (small pure-python test) ---"
pip install --no-cache-dir httpx
echo "httpx_rc=$?"
python3 -c "import httpx; print('httpx ok:', httpx.__version__)"
echo "--- dry-run: mobilerun dependency resolution ---"
pip install --dry-run --no-cache-dir mobilerun 2>&1 | tail -20
echo "dryrun_rc=$?"
echo "--- python & pip versions ---"
python3 --version
pip3 --version
echo "=== done: $(date) ==="
