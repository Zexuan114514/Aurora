"""游戏库的持久化存储。"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from . import config


class Library:
    """线程安全的 JSON 游戏库。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.LIBRARY_FILE
        self._lock = threading.RLock()
        raw = config.read_json(self.path, {}) or {}
        self._games: list[dict] = list(raw.get("games") or [])
        self.settings: dict = {**config.DEFAULT_SETTINGS, **(raw.get("settings") or {})}
        self._normalize()

    # ------------------------------------------------------------------ #
    def _normalize(self) -> None:
        for game in self._games:
            game.setdefault("id", uuid.uuid4().hex[:12])
            game.setdefault("images", [])
            game.setdefault("launch_args", "")
            game.setdefault("play_time", 0)
            game.setdefault("last_played", 0)
            game.setdefault("favorite", False)
            game.setdefault("metadata_state", "pending")
            game.setdefault("background", "")
            game.setdefault("background_kind", "")
            game.setdefault("cover_sources", [])
            game.setdefault("custom_icon", "")
            game.setdefault("data_source", "")
            game.setdefault("source_id", "")
            game.setdefault("source_url", "")
            game.setdefault("name_cn", "")
            game.setdefault("name_original", "")
            game.setdefault("rating", "")
            # 简介翻译：description 始终是展示值；_original 存源语言原文；_translated 存译文
            game.setdefault("description_original", "")
            game.setdefault("description_translated", "")
            game.setdefault("description_lang", "")
            game.setdefault("bg_scale", 1.0)
            game.setdefault("bg_x", 0.0)
            game.setdefault("bg_y", 0.0)
            # 会话标记：用于「关掉启动器后游戏仍在运行」时补记时长
            game.setdefault("play_started_at", 0)
            game.setdefault("play_pid", 0)
            game.setdefault("play_heartbeat", 0)
            game.setdefault("play_launcher_pid", 0)
            game.setdefault("play_count", 0)
            game.setdefault("sessions", [])
            # 转区启动（Locale Emulator）
            game.setdefault("locale_enabled", False)
            game.setdefault("locale_guid", "")

    def save(self) -> None:
        with self._lock:
            config.write_json(
                self.path,
                {"version": 1, "games": self._games, "settings": self.settings},
            )

    # ------------------------------------------------------------------ #
    def all(self) -> list[dict]:
        with self._lock:
            return [dict(g) for g in self._games]

    def get(self, game_id: str) -> dict | None:
        with self._lock:
            for game in self._games:
                if game["id"] == game_id:
                    return game
        return None

    def find_by_exe(self, exe: str) -> dict | None:
        target = str(Path(exe)).lower()
        with self._lock:
            for game in self._games:
                if str(game.get("exe", "")).lower() == target:
                    return game
        return None

    def add(self, record: dict) -> dict:
        with self._lock:
            self._games.append(record)
            self.save()
        return record

    def update(self, game_id: str, **fields) -> dict | None:
        with self._lock:
            game = self.get(game_id)
            if game is None:
                return None
            game.update(fields)
            self.save()
            return game

    def remove(self, game_id: str) -> bool:
        with self._lock:
            before = len(self._games)
            self._games = [g for g in self._games if g["id"] != game_id]
            changed = len(self._games) != before
            if changed:
                self.save()
            return changed

    def touch_played(self, game_id: str, seconds: float = 0) -> None:
        with self._lock:
            game = self.get(game_id)
            if game is None:
                return
            game["last_played"] = int(time.time())
            if seconds > 0:
                game["play_time"] = int(game.get("play_time", 0) + seconds)
            self.save()

    def set_setting(self, key: str, value) -> dict:
        with self._lock:
            self.settings[key] = value
            self.save()
            return dict(self.settings)
