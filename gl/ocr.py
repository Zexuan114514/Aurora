"""兼容层：ocr 已搬到 `aurora.platform.ocr`（P3.9），这里是**透明模块别名**。

用 sys.modules 替换（而不是逐个复制名字），这样读写模块级状态、以及给模块打补丁
（如 tools/vntext_probe.py 模拟「没装日语」时改 ocr._langs）都会作用到同一份实现上。
"""
from __future__ import annotations

import sys

from aurora.platform import ocr as _impl

sys.modules[__name__] = _impl
