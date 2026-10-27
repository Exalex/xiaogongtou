#!/system/bin/sh
# deploy_pi_files.sh — 部署 pi 手机侧文件（root 执行；源目录 /data/local/tmp/pideploy）
PREFIX=/data/data/com.termux/files/usr
H=/data/data/com.termux/files/home
TU=$(stat -c %u $H)
SRC=/data/local/tmp/pideploy

mkdir -p $H/.pi/agent/skills/phone-control $H/pi-work/out $H/bridge/tools

cp $SRC/models.json   $H/.pi/agent/models.json
cp $SRC/settings.json $H/.pi/agent/settings.json
cp $SRC/pi            $H/pi-runtime/pi
cp $SRC/AGENTS.md     $H/pi-work/AGENTS.md
cp $SRC/ptool.py      $H/bridge/tools/ptool.py
cp $SRC/skills/phone-control/SKILL.md $H/.pi/agent/skills/phone-control/SKILL.md

chmod 755 $H/pi-runtime/pi $H/bridge/tools/ptool.py
chmod 644 $H/.pi/agent/models.json $H/.pi/agent/settings.json \
          $H/pi-work/AGENTS.md $H/.pi/agent/skills/phone-control/SKILL.md
chown -R $TU:$TU $H/.pi/agent/skills $H/pi-work $H/bridge/tools 2>/dev/null

echo "== deployed (uid=$(id -u)) =="
ls -la $H/pi-runtime/pi $H/.pi/agent/models.json $H/.pi/agent/settings.json \
       $H/pi-work/AGENTS.md $H/bridge/tools/ptool.py $H/.pi/agent/skills/phone-control/SKILL.md
echo "== done =="
