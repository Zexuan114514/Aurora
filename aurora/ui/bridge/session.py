"""启动 / 会话 / 下载扫描桥接（P3.5 从 gl/api.py 原样搬出）。

覆盖：启动（含转区命令拼装）、进程树回调、会话结算与崩溃恢复、心跳、结束游戏、下载目录扫描。
方法体逐字未改；`gl` 依赖在 P3.6 收口到 aurora.infra / aurora.platform。
"""
from __future__ import annotations

import time
from pathlib import Path

from aurora.domain import session_rules
from aurora.ui.bridge.shared import _public
from gl import config, locale, process   # TODO(P3.6): 收口


class SessionBridgeMixin:
    """启动与结束游戏、会话记账与恢复、下载目录扫描。"""


    def scan_downloads(self) -> dict:
        return self._launch.scan_downloads()


    def set_game_locale(self, game_id: str, enabled: bool, guid: str='') -> dict:
        return self._launch.set_game_locale(game_id, enabled, guid)


    # ------------------------------------------------------------------ #
    # 运行
    # ------------------------------------------------------------------ #
    def launch(self, game_id: str) -> dict:
        return self._launch.launch(game_id)


    def _locale_command(self, game: dict) -> tuple[list[str] | None, str]:
        return self._launch._locale_command(game)


    def _on_game_found(self, game_id: str, pid: int) -> None:
        return self._launch._on_game_found(game_id, pid)


    def _on_game_exit(self, game_id: str, seconds: float) -> None:
        return self._launch._on_game_exit(game_id, seconds)


    def stop(self, game_id: str) -> dict:
        return self._launch.stop(game_id)


    def _start_heartbeat(self) -> None:
        return self._launch._start_heartbeat()


    def _beat(self) -> None:
        return self._launch._beat()


    def _recover_sessions(self) -> None:
        return self._launch._recover_sessions()
