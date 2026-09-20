"""应用层端口（Protocol）：用例依赖这些抽象，不依赖具体适配器。

P2 只定义「状态存储」与「时钟」两个端口 —— 它们正好是数据 v2 需要的；
其余端口（MetadataSource / TextSource / Translator / TaskRunner…）在 P3 随服务一起补。
"""
from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable


class LoadReport(TypedDict, total=False):
    """一次装载的结果，给界面与诊断用。"""

    layout: str
    games: int
    bookshelves: int
    settings: int
    sessions: int
    backup: str
    notes: list[str]


class ImportReport(TypedDict, total=False):
    added: int
    skipped: int
    shelves_created: int
    games: list[dict]


@runtime_checkable
class Clock(Protocol):
    """时间来源：让会话结算、缓存 TTL、去抖在测试里可控。"""

    def now(self) -> float: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class StateStorePort(Protocol):
    """游戏库 / 设置 / 会话历史的持久化端口。

    实现方负责：布局解析、v1→v2 迁移、原子写、去抖单写者、损坏恢复、导入导出；
    调用方（`gl/store.py` 的 `Library` 与后续 app 服务）只操作内存快照 + `mark_dirty()`。
    """

    games: list[dict]
    shelves: list[dict]
    settings: dict

    def load(self) -> LoadReport: ...

    def mark_dirty(self, *, settings_only: bool = False) -> None: ...

    def flush(self, *, timeout: float = 5.0) -> None: ...

    def close(self) -> None: ...

    def append_session(self, game_id: str, record: dict) -> None: ...

    def export_payload(self, *, redact: bool = True) -> dict: ...

    def merge_import(self, payload: dict) -> ImportReport: ...
