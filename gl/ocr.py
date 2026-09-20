"""兼容层：ocr 已搬到 `aurora.platform.ocr`（P3.9），这里保留同名转发。"""
from __future__ import annotations

from aurora.platform.ocr import (  # noqa: F401  (re-export)
    _lock,
    _import_error,
    _mods,
    available,
    languages,
    has_language,
    real_tag,
    status,
    _engine,
    bmp_bytes,
    recognize_bgr,
)
