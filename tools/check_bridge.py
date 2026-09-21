"""交叉检查前端调用与后端方法名是否一一对应（人读版）。

机器读的版本是 `tools/checks/check_contract.py`（对快照逐点比对，CI 里跑）；
这个脚本留给人肉排查：把「前端调了哪些、后端有哪些、缺哪些」直接打出来。

**为什么重写**（旧版在 P3/P4 之后必然假红）：它只正则扫 `gl/web/app.js` 与
`gl/api.py` 两个文件，而重构之后前端调用点散在 `gl/web/app/**/*.js`、桥接方法
散在 `aurora/ui/bridge/*.py`，两处都成了薄壳 —— 实测跑出来是「后端缺失
apply_window_icon, refresh_running」+ 退出码 1，全是假警报。现在扫描面与离线检查
共用 `tools/checks/common.py` 的解析，不再各自维护正则。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "checks"))

from common import class_methods, frontend_calls  # noqa: E402

API = "gl/api.py"
APP_JS = ROOT / "gl" / "web" / "app.js"
MODULES = sorted((ROOT / "gl" / "web" / "app").rglob("*.js"))
OVERLAY_HTML = ROOT / "gl" / "web" / "overlay.html"


def overlay_actions() -> set[str]:
    """悬浮窗页面通过 `api.<动作>(...)` 调用的动作（不走 call() 包装）。"""
    try:
        text = OVERLAY_HTML.read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(re.findall(r"\bapi\.([A-Za-z_]\w*)\s*\(", text))


def main() -> int:
    methods = {name for name in class_methods(API, "Api") if not name.startswith("_")}
    actions = overlay_actions()
    called = frontend_calls(APP_JS, *MODULES) | actions
    missing = sorted(called - methods)
    unused = sorted(methods - called)

    print(f"后端公开方法 {len(methods)} 个；前端调用点 {len(called)} 个"
          f"（页面模块 {len(MODULES)} 个 + 悬浮窗 {len(actions)} 个动作）")
    print()
    print("后端缺失:", ", ".join(missing) or "无")
    print("前端未用:", ", ".join(unused) or "无")
    print("（「前端未用」不判失败：有的方法只给悬浮窗/命令行/未来界面用）")
    if missing:
        print()
        print("前端调用了后端不存在的方法——先补后端，或改前端调用名。")
        return 1
    print()
    print(f"结论：前端 {len(called)} 个调用点全部有后端实现")
    return 0


if __name__ == "__main__":
    sys.exit(main())
