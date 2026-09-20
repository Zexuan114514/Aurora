"""兼容层：gameinput 已搬到 `aurora.platform.gameinput`（P3.8），这里保留同名转发。"""
from __future__ import annotations

from aurora.platform.gameinput import (  # noqa: F401  (re-export)
    user32,
    VK_RETURN,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    ensure_dpi_awareness,
    foreground,
    clickable,
    advance,
)
