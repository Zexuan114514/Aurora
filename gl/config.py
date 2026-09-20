"""兼容层：config 已搬到 `aurora.infra.config`（P3.9-g），这里是透明模块别名。"""
from __future__ import annotations

import sys

from aurora.infra import config as _impl

sys.modules[__name__] = _impl
