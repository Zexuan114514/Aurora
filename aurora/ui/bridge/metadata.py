"""元数据桥接：重抓 / Steam 导入 / 搜索匹配 / 简介翻译（P3.4 从 gl/api.py 原样搬出）。

方法体逐字未改。
"""
from __future__ import annotations


import json
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

import webview

from aurora.ui.bridge.shared import _public, _resolve_note
from gl import (config, detect, downloads, gameinput, hookfinder, hotkey, linetrans, locale,
                netproxy, ocr, overlay, process, screencap, steamlib, translate, vntext,
                winapi)   # TODO(P3.5): 逐个收口到 aurora.infra / aurora.platform
from gl.sources import SourceManager


class MetadataBridgeMixin:
    """资料源搜索与匹配、Steam 库导入、简介翻译（单条与批量）。"""


    # ------------------------------------------------------------------ #
    # 批量维护 / 迁移
    # ------------------------------------------------------------------ #
    def refresh_all_metadata(self) -> dict:
        return self._metadata.refresh_all_metadata()


    def _refresh_all_worker(self, ids: list[str]) -> None:
        return self._metadata._refresh_all_worker(ids)


    # ------------------------------------------------------------------ #
    # Steam 库
    # ------------------------------------------------------------------ #
    def scan_steam(self) -> dict:
        return self._metadata.scan_steam()


    def import_steam_games(self, items: list[dict]) -> dict:
        return self._metadata.import_steam_games(items)


    def _steam_worker(self, items: list[dict]) -> None:
        return self._metadata._steam_worker(items)


    # ------------------------------------------------------------------ #
    # 元数据搜索
    # ------------------------------------------------------------------ #
    def _auto_search_async(self, game_id: str) -> None:
        return self._metadata._auto_search_async(game_id)


    def _auto_search(self, game_id: str) -> None:
        return self._metadata._auto_search(game_id)


    def search(self, game_id: str, query: str | None=None, auto_apply: bool=False, all_sources: bool=True) -> dict:
        return self._metadata.search(game_id, query, auto_apply, all_sources)


    def apply_candidate(self, game_id: str, source_id: str, candidate_id: str, name: str='', kind: str='manual') -> dict:
        return self._metadata.apply_candidate(game_id, source_id, candidate_id, name, kind)


    def apply_appid(self, game_id: str, appid: int, source: str='manual') -> dict:
        return self._metadata.apply_appid(game_id, appid, source)


    def _apply_source(self, game_id: str, source_id: str, candidate_id: str, name: str='', source: str='auto', score: float | None=None, query: str='') -> None:
        return self._metadata._apply_source(game_id, source_id, candidate_id, name, source, score, query)


    # ------------------------------------------------------------------ #
    # 简介翻译
    # ------------------------------------------------------------------ #
    def _translate_async(self, game_id: str, force: bool=False) -> None:
        return self._translation._translate_async(game_id, force)


    def _translate_queue_loop(self) -> None:
        return self._translation._translate_queue_loop()


    def _translate_description(self, game_id: str) -> dict:
        return self._translation._translate_description(game_id)


    def translate_game(self, game_id: str) -> dict:
        return self._translation.translate_game(game_id)


    def translate_all_descriptions(self) -> dict:
        return self._translation.translate_all_descriptions()


    def _translate_all_worker(self, ids: list[str]) -> None:
        return self._translation._translate_all_worker(ids)


    def test_translation(self, overrides: dict | None=None) -> dict:
        return self._translation.test_translation(overrides)
