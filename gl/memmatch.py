"""兼容层：memmatch 已搬到 `aurora.platform.memmatch`（P3.10），这里是**透明模块别名**。

用 sys.modules 替换（而不是逐个复制名字），这样读写模块级状态、以及给模块打补丁
（如自检脚本预热「热区」缓存）都会作用到同一份实现上。
"""
from __future__ import annotations

import sys

from aurora.platform import memmatch as _impl

sys.modules[__name__] = _impl
