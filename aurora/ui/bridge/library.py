"""游戏库桥接：增删改查 / 分类 / 素材 / 启动参数 / 导入导出（P3.3 从 gl/api.py 原样搬出）。

方法体逐字未改；`gl` 遗留依赖在 P3.4 收口。
"""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

import webview

from aurora.ui.bridge.shared import IMAGE_EXTS, LAUNCHABLE_EXTS, _public
from gl import config, process   # TODO(P3.4): 收口


class LibraryBridgeMixin:
    """游戏库、分类书架、封面/背景/图标素材、库导入导出。"""


    def remove_game(self, game_id: str) -> dict:
        return self._library_service.remove_game(game_id)


    def _purge_assets(self, game_id: str) -> None:
        return self._library_service._purge_assets(game_id)


    def toggle_favorite(self, game_id: str) -> dict:
        return self._library_service.toggle_favorite(game_id)


    # ------------------------------------------------------------------ #
    # 分类书架（多对多）与游玩状态
    # ------------------------------------------------------------------ #
    def _shelves_payload(self) -> dict:
        return self._library_service._shelves_payload()


    def list_shelves(self) -> dict:
        return self._library_service.list_shelves()


    def create_shelf(self, name: str) -> dict:
        return self._library_service.create_shelf(name)


    def rename_shelf(self, shelf_id: str, name: str) -> dict:
        return self._library_service.rename_shelf(shelf_id, name)


    def move_shelf(self, shelf_id: str, delta: int) -> dict:
        return self._library_service.move_shelf(shelf_id, delta)


    def delete_shelf(self, shelf_id: str) -> dict:
        return self._library_service.delete_shelf(shelf_id)


    def _changed_payload(self, changed: list[dict]) -> dict:
        return self._library_service._changed_payload(changed)


    def add_games_to_shelf(self, game_ids: list, shelf_ids: list) -> dict:
        return self._library_service.add_games_to_shelf(game_ids, shelf_ids)


    def remove_games_from_shelf(self, game_ids: list, shelf_id: str) -> dict:
        return self._library_service.remove_games_from_shelf(game_ids, shelf_id)


    def set_games_favorite(self, game_ids: list, value: bool) -> dict:
        return self._library_service.set_games_favorite(game_ids, value)


    def set_game_status(self, game_id: str, status: str) -> dict:
        return self._library_service.set_game_status(game_id, status)


    # ------------------------------------------------------------------ #
    # 自定义名称 / 封面
    # ------------------------------------------------------------------ #
    def rename_game(self, game_id: str, name: str) -> dict:
        return self._library_service.rename_game(game_id, name)


    def reset_name(self, game_id: str) -> dict:
        return self._library_service.reset_name(game_id)


    def set_cover(self, game_id: str, url: str) -> dict:
        return self._library_service.set_cover(game_id, url)


    def clear_custom_cover(self, game_id: str) -> dict:
        return self._library_service.clear_custom_cover(game_id)


    def pick_local_cover(self, game_id: str) -> dict:
        """用本地图片当封面（原图存 data/covers，副本给页面用）。"""
        if self._window is None:
            return {"ok": False}
        if not self._library.get(game_id):
            return {"ok": False, "error": "no-game"}
        result = self._dialogs.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("图片 (*.jpg;*.jpeg;*.png;*.webp;*.bmp)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        source = Path(result[0])
        if source.suffix.lower() not in IMAGE_EXTS:
            return {"ok": False, "error": "unsupported"}
        config.ensure_dirs()
        self._purge_covers(game_id)
        name = f"{game_id}-{uuid.uuid4().hex[:6]}{source.suffix.lower()}"
        try:
            shutil.copy2(source, config.COVER_SOURCE_DIR / name)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        url = f"assets/covers/{name}"
        updated = self._library.update(game_id, custom_cover=url)
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {"ok": True, "game": _public(updated, self._pm) if updated else None}


    def _purge_covers(self, game_id: str) -> None:
        return self._library_service._purge_covers(game_id)


    # ------------------------------------------------------------------ #
    # 背景
    # ------------------------------------------------------------------ #
    def set_background(self, game_id: str, url: str, kind: str='remote') -> dict:
        return self._library_service.set_background(game_id, url, kind)


    def clear_background(self, game_id: str) -> dict:
        return self._library_service.clear_background(game_id)


    def set_background_view(self, game_id: str, scale: float, x: float, y: float) -> dict:
        return self._library_service.set_background_view(game_id, scale, x, y)


    def pick_local_background(self, game_id: str) -> dict:
        if self._window is None:
            return {"ok": False}
        result = self._dialogs.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("图片 (*.jpg;*.jpeg;*.png;*.webp;*.bmp)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        source = Path(result[0])
        if source.suffix.lower() not in IMAGE_EXTS:
            return {"ok": False, "error": "unsupported"}
        config.ensure_dirs()
        name = f"{game_id}-{uuid.uuid4().hex[:6]}{source.suffix.lower()}"
        try:
            shutil.copy2(source, config.BG_SOURCE_DIR / name)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        url = f"assets/backgrounds/{name}"
        game = self._library.update(game_id, background=url, background_kind="local")
        if game:
            self._emit("game:updated", _public(game, self._pm))
        return {"ok": True, "game": _public(game, self._pm) if game else None}


    # ------------------------------------------------------------------ #
    # 自定义图标
    # ------------------------------------------------------------------ #
    def pick_custom_icon(self, game_id: str) -> dict:
        """让用户给某个游戏挑一张自定义图标（同时会用作窗口/任务栏图标）。"""
        if self._window is None:
            return {"ok": False}
        if not self._library.get(game_id):
            return {"ok": False, "error": "no-game"}
        result = self._dialogs.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("图片 (*.png;*.jpg;*.jpeg;*.webp;*.ico;*.bmp)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        return self._set_custom_icon(game_id, Path(result[0]))


    def _set_custom_icon(self, game_id: str, source: Path) -> dict:
        if not source.is_file():
            return {"ok": False, "error": "missing"}
        suffix = source.suffix.lower()
        if suffix not in IMAGE_EXTS + (".ico",):
            return {"ok": False, "error": "unsupported"}

        config.ensure_dirs()
        self._remove_icon_files(game_id)
        name = f"{game_id}{suffix}"
        try:
            shutil.copy2(source, config.ICON_SOURCE_DIR / name)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        url = f"assets/icons/{name}?v={int(time.time())}"
        updated = self._library.update(game_id, custom_icon=url)
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
            self.apply_window_icon(game_id)
        return {"ok": True, "game": _public(updated, self._pm) if updated else None}


    def clear_custom_icon(self, game_id: str) -> dict:
        return self._library_service.clear_custom_icon(game_id)


    def _remove_icon_files(self, game_id: str) -> None:
        return self._library_service._remove_icon_files(game_id)


    def set_launch_args(self, game_id: str, args: str) -> dict:
        return self._library_service.set_launch_args(game_id, args)


    def refresh_running(self) -> dict:
        return self._library_service.refresh_running()


    def export_library(self) -> dict:
        """导出游戏库为一份 JSON（换机 / 备份用）。"""
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._dialogs.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="aurora-library.json",
            file_types=("JSON 文件 (*.json)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        target = Path(result[0] if isinstance(result, (list, tuple)) else result)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        # 导出走 StateStore：带上 schema_version，并剥离密钥（ADR-0011）
        payload = self._library.export_payload(redact=True)
        games = payload["games"]
        try:
            config.write_json(target, payload)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        config.log(f"library exported: {len(games)} games -> {target}")
        return {"ok": True, "path": str(target), "games": len(games)}


    def import_library(self) -> dict:
        """从导出的 JSON 里合并游戏（按 exe 路径去重，不动已有条目）。"""
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._dialogs.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("JSON 文件 (*.json)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        source = Path(result[0] if isinstance(result, (list, tuple)) else result)
        data = config.read_json(source, None)
        if not isinstance(data, dict) or not isinstance(data.get("games"), list):
            return {"ok": False, "error": "bad-file"}

        # 合并逻辑归 StateStore（分类同名合并、按 exe 去重、不覆盖已有条目）
        report = self._library.merge_import(data)
        if report.get("error"):
            return {"ok": False, "error": report["error"]}
        added = [_public(record, self._pm) for record in (report.get("games") or [])]
        skipped = int(report.get("skipped") or 0)
        if added:
            self._emit("games:imported", {"games": added,
                                          "ids": [g["id"] for g in added], "ignored": skipped})
        config.log(f"library imported: +{len(added)} / skipped={skipped}")
        return {"ok": True, "added": len(added), "skipped": skipped, "games": added,
                **self._shelves_payload()}


    def _scan_folder(self, folder: Path, limit: int) -> list[str]:
        return self._library_service._scan_folder(folder, limit)


    def _expand_dropped(self, paths: list[str]) -> tuple[list[str], int]:
        return self._library_service._expand_dropped(paths)


    def import_dropped(self, paths: list[str]) -> dict:
        return self._library_service.import_dropped(paths)


    def add_by_path(self, path: str) -> dict:
        return self._library_service.add_by_path(path)


    def _import_one(self, path: str, auto_search: bool | None=None) -> dict | None:
        return self._library_service._import_one(path, auto_search)
