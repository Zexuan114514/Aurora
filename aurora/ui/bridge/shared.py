"""桥接层共享的投影与常量（P3.3 从 gl/api.py 原样搬出）。

`_public()` 把内部游戏记录投影成前端契约（它的字段集就是前端读到的东西）。
"""
from __future__ import annotations

from pathlib import Path

from aurora.app.projection import _public  # noqa: F401  (P3.8 上移到 app 层，这里保留转发)
from gl import process   # TODO(P3.8): 仅用于类型标注，收口后改 Protocol


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
#: 可以直接启动的文件类型（.bat/.cmd 会经 cmd.exe 拉起，见 gl/process.py）
LAUNCHABLE_EXTS = (".exe", ".bat", ".cmd")

NOTES = {
    "network": "网络请求失败，请检查网络后重试",
    "no-results": "所有资料源里都没有找到对应条目",
    "low-confidence": "匹配置信度不足，请手动选择",
    "no-query": "文件名信息太少，请手动搜索确认",
}


def _resolve_note(reason: str | None) -> str:
    return NOTES.get(reason or "", "未找到匹配的商店条目")


