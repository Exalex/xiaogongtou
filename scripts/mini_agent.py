#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""转发壳 —— 真源在 ../tabletbrain/，这个文件不含任何逻辑。

2026-10-28 收敛：这里原本是一份独立副本（3309 行），和 tabletbrain/ 的同名文件
（4359 行）差了 1050 行，两边都有人改过 —— 改错边等于白改。现在统一为一个真源，
本文件只做三件事：

  1. 把 ../tabletbrain 插到 sys.path 最前（真源里的 `import scripts_lib` 才能找到真源）
  2. 把 __file__ 指向真源路径（将来真源若用 __file__ 算相对路径也不会错）
  3. exec 真源同名文件（import 与直接运行走同一条路，行为完全一致）

**不要在 scripts/ 下改代码。要改就改 tabletbrain/ 下那一份。**
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TRUE_DIR = os.path.normpath(os.path.join(_HERE, os.pardir, "tabletbrain"))
_TARGET = os.path.join(_TRUE_DIR, os.path.basename(__file__))

if not os.path.exists(_TARGET):
    raise SystemExit("真源不存在：%s" % _TARGET)

if _TRUE_DIR not in sys.path:
    sys.path.insert(0, _TRUE_DIR)

globals()["__file__"] = _TARGET

with open(_TARGET, encoding="utf-8") as _src_f:
    _SRC = _src_f.read()

exec(compile(_SRC, _TARGET, "exec"), globals())
