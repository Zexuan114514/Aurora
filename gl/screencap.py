"""兼容层：screencap 已搬到 `aurora.platform.screencap`（P3.9），这里保留同名转发。"""
from __future__ import annotations

from aurora.platform.screencap import (  # noqa: F401  (re-export)
    user32,
    gdi32,
    PW_RENDERFULLCONTENT,
    SRCCOPY,
    DIB_RGB_COLORS,
    BITMAPINFOHEADER,
    BITMAPINFO,
    windows_of,
    main_window,
    window_title,
    window_titles,
    is_exposed,
    _grab_bitmap,
    _bgr_from_bgra,
    _looks_blank,
    capture,
    save_png,
)
