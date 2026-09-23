# 把 com.termux 加进 athena 的 no_frozen 白名单（root 运行）
# usage: su -c '/data/data/com.termux/files/usr/bin/python3 /data/local/tmp/db_patch_termux.py'
import sqlite3
import sys

DB = "/data/user_de/0/com.oplus.athena/databases/athena.db"

db = sqlite3.connect(DB)
cur = db.cursor()

cur.execute("SELECT white_list FROM app_frozen WHERE type='no_frozen'")
row = cur.fetchone()
wl = row[0] if row else ""
print("BEFORE tail:", wl[-80:])

if "com.termux" in wl:
    print("ALREADY present, no change")
else:
    wl2 = wl.rstrip(",") + ",com.termux"
    cur.execute("UPDATE app_frozen SET white_list=? WHERE type='no_frozen'", (wl2,))
    db.commit()
    print("PATCHED")

cur.execute("SELECT white_list FROM app_frozen WHERE type='no_frozen'")
print("AFTER tail:", cur.fetchone()[0][-80:])
db.close()
