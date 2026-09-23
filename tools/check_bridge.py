"""交叉检查前端调用与后端方法名是否一一对应（人读版）。

机器读的版本是 `tools/checks/check_contract.py`（对快照逐点比对，CI 里跑）；
这个脚本留给人肉排查：把「前端调了哪些、后端有哪些、缺哪些」直接打出来。

**为什么重写**（旧版在 P3/P4 之后必然假红）：它只正则扫 `gl/web/app.js` 与
`gl/api.py` 两个文件，而重构之后前端调用点散在 `gl/web/app/**/*.js`、桥接方法
散在 `aurora/ui/bridge/*.py`，两处都成了薄壳 —— 实测跑出来是「后端缺失
apply_window_icon, refresh_running」+ 退出码 1，全是假警报。现在扫描面与离线检查
共用 `tools/checks/common.py` 的解析，不再各自维护正则。

**P8.9 删 v1 之后**：扫描面从 `gl/web/**` 换成 `frontend/src`（主窗与悬浮窗分开算）。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "checks"))

from common import class_methods, frontend_calls, frontend_sources  # noqa: E402

API = "gl/api.py"
OVERLAY = "gl/overlay.py"
MAIN_SOURCES = frontend_sources(overlay=False)
OVERLAY_SOURCES = frontend_sources(overlay=True)


def _overlay_source() -> str:
    """定义 OverlayBridge 的文件（P3.9-g 起搬到了 aurora/ui/overlay.py）。"""
    for candidate in ("gl/overlay.py", "aurora/ui/overlay.py"):
        try:
            if "class OverlayBridge" in (ROOT / candidate).read_text(encoding="utf-8"):
                return candidate
        except OSError:
            continue
    return OVERLAY


def main() -> int:
    methods = {name for name in class_methods(API, "Api") if not name.startswith("_")}
    overlay_methods = {name for name in class_methods(_overlay_source(), "OverlayBridge")
                       if not name.startswith("_")}
    # 主窗与悬浮窗是两条独立的桥接通道，分开比（悬浮窗有自己的 js_api）
    calls = frontend_calls(*MAIN_SOURCES)
    overlay_calls = frontend_calls(*OVERLAY_SOURCES)

    missing = sorted(calls - methods)
    unused = sorted(methods - calls)
    overlay_missing = sorted(overlay_calls - overlay_methods)
    overlay_unused = sorted(overlay_methods - overlay_calls)

    print(f"主窗：后端公开方法 {len(methods)} 个；前端调用点 {len(calls)} 个"
          f"（{len(MAIN_SOURCES)} 个源码文件）")
    print(f"悬浮窗：桥接方法 {len(overlay_methods)} 个；调用点 {len(overlay_calls)} 个"
          f"（{len(OVERLAY_SOURCES)} 个源码文件）")
    print()
    print("主窗 · 后端缺失:", ", ".join(missing) or "无")
    print("主窗 · 前端未用:", ", ".join(unused) or "无")
    print("悬浮窗 · 后端缺失:", ", ".join(overlay_missing) or "无")
    print("悬浮窗 · 前端未用:", ", ".join(overlay_unused) or "无")
    print("（「前端未用」不判失败：有的方法只给悬浮窗/命令行/未来界面用）")
    if missing or overlay_missing:
        print()
        print("前端调用了后端不存在的方法——先补后端，或改前端调用名。")
        return 1
    print()
    print(f"结论：前端 {len(calls) + len(overlay_calls)} 个调用点全部有后端实现")
    return 0


if __name__ == "__main__":
    sys.exit(main())
