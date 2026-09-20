"""兼容层：overlay 已搬到 `aurora.ui.overlay`（P3.9-g），这里是透明模块别名。"""
from __future__ import annotations

import sys

from aurora.ui import overlay as _impl

sys.modules[__name__] = _impl
