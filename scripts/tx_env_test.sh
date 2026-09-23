export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export LD_LIBRARY_PATH=$PREFIX/lib
export PATH=$PREFIX/bin:$PATH
export TMPDIR=$PREFIX/tmp
cd "$HOME"

echo "=== whoami/id ==="
id
echo "=== env sanity ==="
echo "PREFIX=$PREFIX"
echo "=== tools available ==="
for t in apt pkg bash python3 pip3 curl git; do
  p=$(command -v $t 2>/dev/null)
  echo "$t -> ${p:-MISSING}"
done
echo "=== HOME listing ==="
ls -la "$HOME" | head -12
echo "=== bridge ok ==="
