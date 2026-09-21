"""给游戏发一次「下一句」（自检脚本共用）。

实现挪到 `gl/gameinput.py` 了（启动器本体也要用），这里只做转发，
老脚本 `from vntext_advance import advance` 照旧可用。
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gl.gameinput import advance, clickable, ensure_dpi_awareness, foreground  # noqa: E402,F401

__all__ = ["advance", "clickable", "ensure_dpi_awareness", "foreground"]
