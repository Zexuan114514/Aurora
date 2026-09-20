"""游戏内翻译与钩子查找桥接（P3.4 从 gl/api.py 原样搬出）。

覆盖翻译面板状态、钩子查找器、悬浮窗动作与术语表；方法体逐字未改。
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


class VnTextBridgeMixin:
    """翻译会话、钩子查找、悬浮窗与术语表。"""


    # ------------------------------------------------------------------ #
    # 游戏内翻译（Textractor 钩子 + 屏幕 OCR）
    # ------------------------------------------------------------------ #
    def _vntext_state(self) -> dict:
        return self._vntext._vntext_state()


    def get_vntext_status(self) -> dict:
        return self._vntext.get_vntext_status()


    def set_vntext_hook(self, game_id: str, code: str) -> dict:
        return self._vntext.set_vntext_hook(game_id, code)


    def set_vntext_option(self, key: str, value) -> dict:
        return self._vntext.set_vntext_option(key, value)


    def start_vntext(self, game_id: str) -> dict:
        return self._vntext.start_vntext(game_id)


    def stop_vntext(self) -> dict:
        return self._vntext.stop_vntext()


    # ------------------------------------------------------------------ #
    # 自研钩子查找器：OCR 取当前台词 → 内存定位 → 调试器 + 硬件断点 → 生成 H-code → 验证
    # ------------------------------------------------------------------ #
    def _hooksearch_state(self) -> dict:
        return self._hooksearch_service._hooksearch_state()


    def _set_hooksearch(self, **patch) -> None:
        return self._hooksearch_service._set_hooksearch()


    def get_hook_search_status(self) -> dict:
        return self._hooksearch_service.get_hook_search_status()


    def advance_game(self, game_id: str) -> dict:
        return self._hooksearch_service.advance_game(game_id)


    def _hooksearch_advance(self, hwnd: int) -> str:
        return self._hooksearch_service._hooksearch_advance(hwnd)


    def start_hook_search(self, game_id: str, text: str='') -> dict:
        return self._hooksearch_service.start_hook_search(game_id, text)


    def stop_hook_search(self) -> dict:
        return self._hooksearch_service.stop_hook_search()


    def _hooksearch_worker(self, game_id: str, pid: int, hwnd: int, text: str) -> None:
        return self._hooksearch_service._hooksearch_worker(game_id, pid, hwnd, text)


    def _hooksearch_on_hit(self, row: dict) -> None:
        return self._hooksearch_service._hooksearch_on_hit(row)


    def _hooksearch_verify_pool(self, game_id: str, pid: int, hwnd: int, pool: list[dict], target: str) -> str:
        return self._hooksearch_service._hooksearch_verify_pool(game_id, pid, hwnd, pool, target)


    def _hooksearch_fail(self, reason: str, message: str) -> None:
        return self._hooksearch_service._hooksearch_fail(reason, message)


    def _hooksearch_try(self, game_id: str, hwnd: int, code: str, target: str) -> bool:
        return self._hooksearch_service._hooksearch_try(game_id, hwnd, code, target)


    def _hooksearch_sample(self, code: str) -> str:
        return self._hooksearch_service._hooksearch_sample(code)


    def close_overlay(self) -> dict:
        return self._vntext.close_overlay()


    def set_vntext_region(self, game_id: str, region: dict) -> dict:
        return self._vntext.set_vntext_region(game_id, region)


    def capture_game_frame(self, game_id: str) -> dict:
        return self._vntext.capture_game_frame(game_id)


    def lock_vntext_thread(self, key: str) -> dict:
        return self._vntext.lock_vntext_thread(key)


    def send_hook_code(self, code: str) -> dict:
        return self._vntext.send_hook_code(code)


    def translate_line_now(self, text: str) -> dict:
        return self._vntext.translate_line_now(text)


    def set_vntext_paused(self, paused: bool) -> dict:
        return self._vntext.set_vntext_paused(paused)


    def clear_vntext_context(self) -> dict:
        return self._vntext.clear_vntext_context()


    def set_overlay_style(self, patch: dict) -> dict:
        return self._vntext.set_overlay_style(patch)


    def set_overlay_click_through(self, on: bool) -> dict:
        return self._vntext.set_overlay_click_through(on)


    def toggle_overlay(self) -> dict:
        return self._vntext.toggle_overlay()


    def list_glossary(self) -> dict:
        return self._vntext.list_glossary()


    def set_glossary_entry(self, source: str, target: str, game_id: str='') -> dict:
        return self._vntext.set_glossary_entry(source, target, game_id)


    def remove_glossary_entry(self, source: str, game_id: str='') -> dict:
        return self._vntext.remove_glossary_entry(source, game_id)


    # ------------------------------------------------------------------ #
    def _on_vntext_line(self, payload: dict) -> None:
        return self._vntext._on_vntext_line(payload)


    def _on_translate_event(self, kind: str, payload: dict) -> None:
        return self._vntext._on_translate_event(kind, payload)


    def _on_overlay_action(self, name: str, payload) -> dict:
        return self._vntext._on_overlay_action(name, payload)


    def _toggle_overlay_click_through(self) -> None:
        return self._vntext._toggle_overlay_click_through()


    def _toggle_overlay_visible(self) -> dict:
        return self._vntext._toggle_overlay_visible()
