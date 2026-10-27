#!/system/bin/sh
# deploy_reliability.sh — 部署「确定性骨架」（三级锚点 + 五道关卡 + 账本种子）
# 前提：/data/local/tmp/xgt_dep 下已 push：
#   anchors.py / scripts_lib.py / mini_agent.py
#   families.json / guards.json / apps.merged.json
#   scripts/weibo_hot_rank_top5.json scripts/kaipanla_limit_up.json
H=/data/data/com.termux/files/home
TMP=/data/local/tmp/xgt_dep
SK=$H/bridge/skills
PY=/data/data/com.termux/files/usr/bin/python3
TS=$(date +%s)

echo "=== 1) 备份账本 ==="
if [ -d "$SK" ]; then
  cp -r $SK $SK.bak.$TS && echo "backup: $SK.bak.$TS"
fi

echo "=== 2) 部署脚本（root:root 700）==="
cp $TMP/anchors.py $H/anchors.py
cp $TMP/scripts_lib.py $H/scripts_lib.py
cp $TMP/mini_agent.py $H/mini_agent.py
chown root:root $H/anchors.py $H/scripts_lib.py $H/mini_agent.py
chmod 700 $H/anchors.py $H/scripts_lib.py $H/mini_agent.py
ls -la $H/anchors.py $H/scripts_lib.py $H/mini_agent.py

echo "=== 3) 部署账本 ==="
mkdir -p $SK/scripts
cp $TMP/families.json $SK/families.json
cp $TMP/guards.json $SK/guards.json
cp $TMP/apps.merged.json $SK/apps.json
cp $TMP/scripts/weibo_hot_rank_top5.json $SK/scripts/
cp $TMP/scripts/kaipanla_limit_up.json $SK/scripts/
chown -R root:root $SK
chmod 644 $SK/*.json
chmod 644 $SK/scripts/*.json
ls -la $SK $SK/scripts

echo "=== 4) 语法校验 ==="
$PY -m py_compile $H/anchors.py $H/scripts_lib.py $H/mini_agent.py && echo "py_compile OK" || echo "py_compile FAILED"

echo "=== 5) 模块自检 ==="
cd $H && $PY -c "
import sys; sys.path.insert(0,'.')
import anchors as A, scripts_lib as S
print('anchors OK, scripts_lib OK')
print('families:', sorted(S.load_families()))
print('scripts:', [s['id'] for s in S.load_scripts()])
cards=S.cards_of({})
w=cards.get('com.sina.weibo') or {}
print('weibo pages:', [p['name'] for p in (w.get('pages') or [])])
" 2>&1 | tail -8

echo "=== 6) 重启控制台 ==="
pkill -f mini_console.py 2>/dev/null
sleep 1
setsid sh /data/adb/mobilerun-console/run.sh </dev/null >>/data/local/tmp/console_supervisor.log 2>&1 &
sleep 4
$PY -c "import urllib.request;r=urllib.request.urlopen('http://127.0.0.1:8900/api/status',timeout=8);print('probe',r.status,r.read().decode()[:160])" || echo "PROBE FAILED"
echo "=== deploy done"
