# -*- coding: utf-8 -*-
"""检查 mini_console.py v2 的完整性：PY 语法 / HTML id 重复 / JS 语法（node --check）"""
import re
import subprocess
import py_compile
from collections import Counter

SRC = r'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/scripts/mini_console.py'
TMP = r'D:/workspace/workbuddySpace/githubResearch/mobilerun-ondevice/scripts/_tmp_ui.js'

py_compile.compile(SRC, doraise=True)
print('1) PY syntax: OK')

src = open(SRC, encoding='utf-8').read()
m = re.search(r'PAGE_HTML = r"""(.*?)"""', src, re.S)
html = m.group(1)
print('2) HTML chars:', len(html))

ids = re.findall(r'id="([^"]+)"', html)
dup = [k for k, v in Counter(ids).items() if v > 1]
print('3) ids:', ids)
print('   dup ids:', dup if dup else 'NONE (OK)')

print('4) script tags: open=%d close=%d' % (html.count('<script>'), html.count('</script>')))

js = re.search(r'<script>(.*?)</script>', html, re.S).group(1)
open(TMP, 'w', encoding='utf-8').write(js)

NODE = r'C:/Users/79475/.workbuddy/binaries/node/versions/22.22.2-3/node.exe'
r = subprocess.run([NODE, '--check', TMP], capture_output=True, text=True)
print('5) node --check rc=%d' % r.returncode)
if r.stderr:
    print(r.stderr[:1200])
else:
    print('   JS syntax: OK')

# 快速抽查关键元素存在
for k in ('favwrap', 'histlist', 'btn-go', 'runcard', 'api/favorites', 'api/history', 'toggleFav', 'renderFavs'):
    print('   has %-14s: %s' % (k, k in html))
