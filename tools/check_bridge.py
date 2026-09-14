"""交叉检查前端调用与后端方法名是否一一对应。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
js = (ROOT / "gl" / "web" / "app.js").read_text(encoding="utf-8")
py = (ROOT / "gl" / "api.py").read_text(encoding="utf-8")

called = set(re.findall(r'call\("([a-z_]+)"', js))
methods = set(re.findall(r"def ([a-z_]+)\(self", py))

missing = sorted(called - methods)
unused = sorted(methods - called)

print("前端调用:", ", ".join(sorted(called)))
print()
print("后端方法:", ", ".join(sorted(methods)))
print()
print("后端缺失:", missing or "无")
print("前端未用:", unused or "无")
sys.exit(1 if missing else 0)
