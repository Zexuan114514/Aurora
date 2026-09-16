"""游戏库的持久化存储。"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from . import config

#: 游戏状态：空 = 未标记
STATUS_VALUES = ("", "playing", "cleared", "shelved")
SHELF_NAME_MAX = 24


class Library:
    """线程安全的 JSON 游戏库。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.LIBRARY_FILE
        self._lock = threading.RLock()
        raw = config.read_json(self.path, {}) or {}
        self._games: list[dict] = list(raw.get("games") or [])
        self._shelves: list[dict] = list(raw.get("bookshelves") or [])
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
            # 游戏内翻译：OCR 识别区域（相对窗口的百分比，窗口缩放/移动后仍有效）
            region = game.get("vntext_ocr_region")
            if not isinstance(region, dict):
                region = {}
            game["vntext_ocr_region"] = {
                "x": float(region.get("x", 0.0) or 0.0),
                "y": float(region.get("y", 0.62) or 0.0),
                "w": float(region.get("w", 1.0) or 1.0),
                "h": float(region.get("h", 0.34) or 0.34),
            }
            # 分类书架（多对多）与游玩状态
            ids = [str(x) for x in (game.get("bookshelf_ids") or []) if str(x)]
            game["bookshelf_ids"] = list(dict.fromkeys(ids))
            if game.get("status") not in STATUS_VALUES:
                game["status"] = ""

        cleaned: list[dict] = []
        seen_names: set[str] = set()
        for shelf in self._shelves:
            name = str(shelf.get("name") or "").strip()
            key = name.lower()
            if not name or key in seen_names:
                continue
            seen_names.add(key)
            cleaned.append({
                "id": str(shelf.get("id") or uuid.uuid4().hex[:12]),
                "name": name[:SHELF_NAME_MAX],
                "created_at": int(shelf.get("created_at") or 0),
            })
        self._shelves = cleaned
        valid = {s["id"] for s in cleaned}
        for game in self._games:   # 分类被删掉后残留的 id 一并清掉
            game["bookshelf_ids"] = [x for x in game["bookshelf_ids"] if x in valid]

    def save(self) -> None:
        with self._lock:
            config.write_json(
                self.path,
                {"version": 1, "games": self._games,
                 "bookshelves": self._shelves, "settings": self.settings},
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

    # ------------------------------------------------------------------ #
    # 分类书架（多对多）
    # ------------------------------------------------------------------ #
    def shelves(self) -> list[dict]:
        with self._lock:
            return [dict(s) for s in self._shelves]

    def shelf_counts(self) -> dict:
        """每个分类里的游戏数 + 未分类数。"""
        with self._lock:
            counts = {s["id"]: 0 for s in self._shelves}
            unfiled = 0
            for game in self._games:
                ids = game.get("bookshelf_ids") or []
                if not ids:
                    unfiled += 1
                for shelf_id in ids:
                    if shelf_id in counts:
                        counts[shelf_id] += 1
            return {"counts": counts, "unfiled": unfiled, "total": len(self._games)}

    def _find_shelf(self, shelf_id: str) -> dict | None:
        for shelf in self._shelves:
            if shelf["id"] == shelf_id:
                return shelf
        return None

    def _name_taken(self, name: str, skip_id: str = "") -> bool:
        key = name.strip().lower()
        return any(s["name"].lower() == key and s["id"] != skip_id for s in self._shelves)

    def create_shelf(self, name: str) -> tuple[dict | None, str]:
        name = str(name or "").strip()
        if not name:
            return None, "empty-name"
        if len(name) > SHELF_NAME_MAX:
            return None, "too-long"
        with self._lock:
            if self._name_taken(name):
                return None, "duplicate"
            shelf = {"id": uuid.uuid4().hex[:12], "name": name,
                     "created_at": int(time.time())}
            self._shelves.append(shelf)
            self.save()
            return dict(shelf), ""

    def rename_shelf(self, shelf_id: str, name: str) -> tuple[bool, str]:
        name = str(name or "").strip()
        if not name:
            return False, "empty-name"
        if len(name) > SHELF_NAME_MAX:
            return False, "too-long"
        with self._lock:
            shelf = self._find_shelf(shelf_id)
            if shelf is None:
                return False, "no-shelf"
            if self._name_taken(name, skip_id=shelf_id):
                return False, "duplicate"
            shelf["name"] = name
            self.save()
            return True, ""

    def move_shelf(self, shelf_id: str, delta: int) -> bool:
        with self._lock:
            index = next((i for i, s in enumerate(self._shelves) if s["id"] == shelf_id), -1)
            if index < 0:
                return False
            target = max(0, min(len(self._shelves) - 1, index + int(delta)))
            if target == index:
                return False
            self._shelves.insert(target, self._shelves.pop(index))
            self.save()
            return True

    def delete_shelf(self, shelf_id: str) -> bool:
        """删除分类只解绑，游戏与游玩记录全部保留。"""
        with self._lock:
            before = len(self._shelves)
            self._shelves = [s for s in self._shelves if s["id"] != shelf_id]
            if len(self._shelves) == before:
                return False
            for game in self._games:
                ids = game.get("bookshelf_ids") or []
                if shelf_id in ids:
                    game["bookshelf_ids"] = [x for x in ids if x != shelf_id]
            self.save()
            return True

    def assign_shelves(self, game_ids: list[str], shelf_ids: list[str],
                       mode: str = "add") -> list[dict]:
        """把游戏加入 / 移出 / 重置分类；返回被改动的游戏。"""
        wanted = [s["id"] for s in self._shelves if s["id"] in set(shelf_ids or [])]
        targets = set(game_ids or [])
        changed: list[dict] = []
        with self._lock:
            for game in self._games:
                if game["id"] not in targets:
                    continue
                current = list(game.get("bookshelf_ids") or [])
                if mode == "remove":
                    new = [x for x in current if x not in wanted]
                elif mode == "set":
                    new = list(wanted)
                else:
                    new = current + [x for x in wanted if x not in current]
                if new != current:
                    game["bookshelf_ids"] = new
                    changed.append(dict(game))
            if changed:
                self.save()
        return changed

    def set_favorite(self, game_ids: list[str], value: bool) -> list[dict]:
        targets = set(game_ids or [])
        changed: list[dict] = []
        with self._lock:
            for game in self._games:
                if game["id"] in targets and bool(game.get("favorite")) != bool(value):
                    game["favorite"] = bool(value)
                    changed.append(dict(game))
            if changed:
                self.save()
        return changed

    def set_status(self, game_id: str, status: str) -> dict | None:
        if status not in STATUS_VALUES:
            return None
        return self.update(game_id, status=status)
