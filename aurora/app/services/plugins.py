"""插件服务（P6.2，ADR-0009）：把 `aurora/infra/plugins.py` 的加载结果收成桥接层要的形状。

分层原因：桥接层不许直接 import infra（见 `tools/checks/check_layers.py`），
所以「扫目录 + 校验 + 加载 + 状态」由本服务承担，桥接只转发。
"""
from __future__ import annotations

from pathlib import Path

from aurora.infra import plugins as loader


class PluginsService:
    """插件目录的懒加载与重新扫描（不热重载已加载实例）。"""

    def __init__(self, data_dir: Path, logger=None) -> None:
        self._dir = Path(data_dir) / "plugins"
        self._logger = logger
        self._cache: list | None = None

    def list(self) -> dict:
        if self._cache is None:
            self._cache = loader.load_all(self._dir, logger=self._logger)
        return self._payload()

    def rescan(self) -> dict:
        self._cache = loader.load_all(self._dir, logger=self._logger)
        return self._payload()

    def statuses(self) -> list:
        """给内部调用方（源码/翻译引擎注册）用的原始状态列表。"""
        self.list()
        return list(self._cache or [])

    def _payload(self) -> dict:
        return {"ok": True, "dir": str(self._dir),
                "plugins": [s.as_dict() for s in (self._cache or [])]}
