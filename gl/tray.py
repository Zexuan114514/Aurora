"""兼容层：tray 已搬到 `aurora.platform.tray`（P3.9-f），这里是透明模块别名。"""
from __future__ import annotations

import sys

from aurora.platform import tray as _impl

sys.modules[__name__] = _impl
