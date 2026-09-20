"""兼容层：proctree 已搬到 `aurora.platform.proctree`（P3.8），这里保留同名转发。"""
from __future__ import annotations

from aurora.platform.proctree import (  # noqa: F401  (re-export)
    TH32CS_SNAPPROCESS,
    MAX_PATH,
    PROCESSENTRY32W,
    _kernel32,
    _INVALID_HANDLE,
    snapshot,
    descendants,
    matching_pids,
    is_alive,
)
