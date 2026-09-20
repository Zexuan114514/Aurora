"""游戏库用例服务（P3.8）：增删改查 / 分类书架 / 状态与收藏 / 素材字段。

方法体从 aurora/ui/bridge/library.py 原样搬出，只把 `self._emit(...)` 改成向默认总线发布
（Api 的通配订阅会把它推给前端）。打开文件对话框的 pick_* 与导入流程仍留在桥接层。
"""
from __future__ import annotations

from aurora.app.events import default_bus
from aurora.app.projection import _public
from aurora.ui.bridge.shared import LAUNCHABLE_EXTS
from gl import config, detect   # TODO(P3.8): 收口到 aurora.infra
import shutil
import time
import uuid
from pathlib import Path


class LibraryService:
    """游戏库数据用例（不含文件对话框与导入扫描）。"""



    #: 一次拖放最多导入多少个 exe，避免误拖整个盘符时炸库
    MAX_DROPPED = 40
    #: 拖入文件夹时最多向下找几层（游戏常见是 <游戏名>\Game\xxx.exe）
    DROP_MAX_DEPTH = 3
    #: 明显不是游戏启动器的目录，不往里翻
    DROP_SKIP_DIRS = {
        "$recycle.bin", "system volume information", "windows", "appdata",
        "program files", "program files (x86)", "programdata", "node_modules",
        ".git", ".svn", "__pycache__", "redist", "_commonredist", "commonredist",
        "directx", "vcredist", "dotnet", "support", "docs", "documentation",
    }
    #: 安装器 / 卸载器之类的可执行文件，不是游戏本体
    DROP_SKIP_EXES = {
        "unins000.exe", "unins001.exe", "unins002.exe", "dxsetup.exe",
        "setup.exe", "install.exe", "installer.exe", "vcredist_x64.exe",
        "vcredist_x86.exe", "unitycrashhandler32.exe", "unitycrashhandler64.exe",
        "crashreportclient.exe", "ue4prereqsetup_x64.exe", "python.exe",
    }

    def __init__(self, library, pm, *, auto_search_async=None,
                 apply_window_icon=None) -> None:
        self._library = library
        self._pm = pm
        #: 导入后触发自动匹配（MetadataService 提供；用 lambda 注入以免装配顺序耦合）
        self._auto_search_async = auto_search_async
        self._apply_window_icon = apply_window_icon

    def list_shelves(self) -> dict:
        return self._shelves_payload()

    def create_shelf(self, name: str) -> dict:
        shelf, error = self._library.create_shelf(name)
        if shelf is None:
            return {"ok": False, "error": error, **self._shelves_payload()}
        return {"ok": True, "shelf": shelf, **self._shelves_payload()}

    def rename_shelf(self, shelf_id: str, name: str) -> dict:
        ok, error = self._library.rename_shelf(shelf_id, name)
        return {"ok": ok, "error": error, **self._shelves_payload()}

    def move_shelf(self, shelf_id: str, delta: int) -> dict:
        ok = self._library.move_shelf(shelf_id, int(delta))
        return {"ok": ok, **self._shelves_payload()}

    def delete_shelf(self, shelf_id: str) -> dict:
        """删除分类只解绑，游戏与游玩记录都保留。"""
        ok = self._library.delete_shelf(shelf_id)
        # 解绑信息前端自己就能推出来（把该 id 从每个游戏的 bookshelf_ids 里摘掉）
        return {"ok": ok, "removed": shelf_id, **self._shelves_payload()}

    def _shelves_payload(self) -> dict:
        stats = self._library.shelf_counts()
        shelves = []
        for shelf in self._library.shelves():
            shelves.append({**shelf, "count": int(stats["counts"].get(shelf["id"], 0))})
        return {"ok": True, "shelves": shelves, "unfiled": int(stats["unfiled"]),
                "total": int(stats["total"])}

    def _changed_payload(self, changed: list[dict]) -> dict:
        return {**self._shelves_payload(),
                "ok": True, "count": len(changed),
                "games": [_public(g, self._pm) for g in changed]}

    def add_games_to_shelf(self, game_ids: list, shelf_ids: list) -> dict:
        changed = self._library.assign_shelves(list(game_ids or []), list(shelf_ids or []),
                                               mode="add")
        return self._changed_payload(changed)

    def remove_games_from_shelf(self, game_ids: list, shelf_id: str) -> dict:
        changed = self._library.assign_shelves(list(game_ids or []), [shelf_id], mode="remove")
        return self._changed_payload(changed)

    def set_games_favorite(self, game_ids: list, value: bool) -> dict:
        changed = self._library.set_favorite(list(game_ids or []), bool(value))
        return self._changed_payload(changed)

    def set_game_status(self, game_id: str, status: str) -> dict:
        updated = self._library.set_status(game_id, str(status or ""))
        if updated is None:
            return {"ok": False, "error": "bad-status"}
        default_bus().publish("game:updated", _public(updated, self._pm))
        return {"ok": True, "game": _public(updated, self._pm)}

    def toggle_favorite(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        updated = self._library.update(game_id, favorite=not bool(game.get("favorite")))
        if updated:
            default_bus().publish("game:updated", _public(updated, self._pm))
        return {
            "ok": bool(updated),
            "favorite": bool(updated.get("favorite")) if updated else False,
            "game": _public(updated, self._pm) if updated else None,
        }

    def rename_game(self, game_id: str, name: str) -> dict:
        """手动改名。改过之后重新匹配也不会被覆盖（name_locked）。"""
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "empty"}
        updated = self._library.update(game_id, name=name[:120], name_locked=True)
        if updated:
            default_bus().publish("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    def reset_name(self, game_id: str) -> dict:
        """恢复成自动匹配的名字，并重新搜一次。"""
        updated = self._library.update(game_id, name_locked=False)
        if not updated:
            return {"ok": False}
        self._auto_search_async(game_id)
        return {"ok": True, "game": _public(updated, self._pm)}

    def set_launch_args(self, game_id: str, args: str) -> dict:
        game = self._library.update(game_id, launch_args=args or "")
        return {"ok": bool(game)}

    def refresh_running(self) -> dict:
        return {"running": self._pm.running_ids()}

    def set_background_view(self, game_id: str, scale: float, x: float, y: float) -> dict:
        """保存背景的缩放与平移（仅写入磁盘，不推送事件，避免拖拽时反复重绘）。"""
        game = self._library.update(
            game_id,
            bg_scale=max(1.0, min(float(scale), 4.0)),
            bg_x=float(x),
            bg_y=float(y),
        )
        return {"ok": bool(game)}

    def clear_custom_cover(self, game_id: str) -> dict:
        self._purge_covers(game_id)
        updated = self._library.update(game_id, custom_cover="")
        if updated:
            default_bus().publish("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    def set_cover(self, game_id: str, url: str) -> dict:
        """把某张图设为封面（url 一般来自该游戏的图片列表）。"""
        updated = self._library.update(game_id, custom_cover=url or "")
        if updated:
            default_bus().publish("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    def clear_background(self, game_id: str) -> dict:
        game = self._library.update(game_id, background="", background_kind="")
        if game:
            default_bus().publish("game:updated", _public(game, self._pm))
        return {"ok": bool(game), "game": _public(game, self._pm) if game else None}

    def set_background(self, game_id: str, url: str, kind: str = "remote") -> dict:
        game = self._library.update(game_id, background=url, background_kind=kind)
        if game:
            default_bus().publish("game:updated", _public(game, self._pm))
        return {"ok": bool(game), "game": _public(game, self._pm) if game else None}

    def clear_custom_icon(self, game_id: str) -> dict:
        self._remove_icon_files(game_id)
        updated = self._library.update(game_id, custom_icon="")
        if updated:
            default_bus().publish("game:updated", _public(updated, self._pm))
            self._apply_window_icon("")
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    # ---- 导入流程（P3.8-h 从桥接层搬出） ----

    def _scan_folder(self, folder: Path, limit: int) -> list[str]:
        """在文件夹里找 .exe（有限深度，跳过明显的杂项目录）。"""
        found: list[str] = []
        stack: list[tuple[Path, int]] = [(folder, 0)]
        while stack and len(found) < limit:
            current, depth = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if len(found) >= limit:
                    break
                try:
                    if entry.is_dir():
                        if depth < self.DROP_MAX_DEPTH and \
                                entry.name.lower() not in self.DROP_SKIP_DIRS:
                            stack.append((entry, depth + 1))
                    elif entry.is_file() and entry.suffix.lower() == ".exe" and \
                            entry.name.lower() not in self.DROP_SKIP_EXES:
                        found.append(str(entry))
                except OSError:
                    continue
        return found

    def _expand_dropped(self, paths: list[str]) -> tuple[list[str], int]:
        """把拖入的条目展开成 exe 列表，返回 (exe 列表, 被忽略的数量)。"""
        found: list[str] = []
        ignored = 0
        for raw in paths or []:
            if not raw:
                continue
            path = Path(str(raw))
            try:
                if path.is_file() and path.suffix.lower() in LAUNCHABLE_EXTS:
                    if str(path) not in found:
                        found.append(str(path))
                elif path.is_dir():
                    hits = self._scan_folder(path, self.MAX_DROPPED - len(found))
                    if hits:
                        for hit in hits:
                            if str(hit) not in found:
                                found.append(str(hit))
                    else:
                        ignored += 1
                else:
                    ignored += 1
            except OSError:
                ignored += 1
        return found[:self.MAX_DROPPED], ignored

    def import_dropped(self, paths: list[str]) -> dict:
        """处理拖进窗口的文件/文件夹（由 main.py 注册的 drop 监听调用）。"""
        exes, ignored = self._expand_dropped(paths or [])
        if not exes:
            return {"ok": False, "error": "no-exe", "ignored": ignored}
        games = [g for g in (self._import_one(exe) for exe in exes) if g]
        default_bus().publish("games:imported", {
            "games": games,
            "ids": [g["id"] for g in games],
            "ignored": ignored,
        })
        config.log(f"dropped import: {len(games)} game(s), ignored={ignored}")
        return {"ok": bool(games), "games": games, "ignored": ignored}

    def add_by_path(self, path: str) -> dict:
        game = self._import_one(path)
        if game is None:
            return {"ok": False, "error": "invalid", "path": path}
        return {"ok": True, "game": game}

    def _import_one(self, path: str, auto_search: bool | None = None) -> dict | None:
        exe = Path(path)
        if not exe.is_file():
            return None
        existing = self._library.find_by_exe(str(exe))
        if existing:
            self._auto_search_async(existing["id"])
            return _public(existing, self._pm)

        info = detect.describe_path(exe)
        record = {
            "id": uuid.uuid4().hex[:12],
            "exe": str(exe),
            "name": info["candidates"][0] if info["candidates"] else exe.stem,
            "exe_stem": info["exe_stem"],
            "dir_name": info["dir_name"],
            "queries": info["queries"],
            "strong_queries": info["strong_queries"],
            "added_at": int(time.time()),
            "metadata_state": "pending",
            "background": "",
            "images": [],
        }
        self._library.add(record)
        config.log(f"imported {exe} -> queries={info['queries']}")
        if auto_search is None:
            auto_search = bool(self._library.settings.get("auto_search", True))
        if auto_search:
            self._auto_search_async(record["id"])
        return _public(record, self._pm)

    def remove_game(self, game_id: str) -> dict:
        ok = self._library.remove(game_id)
        if ok:
            self._purge_assets(game_id)
        return {"ok": ok}

    def _purge_assets(self, game_id: str) -> None:
        """删除该游戏产生的本地素材副本（自定义图标 + 本地背景图）。"""
        self._remove_icon_files(game_id)
        self._purge_covers(game_id)
        for folder in (config.BG_SOURCE_DIR, config.USER_BG_DIR):
            try:
                for item in folder.glob(f"{game_id}-*"):
                    if item.is_file():
                        item.unlink()
            except Exception as exc:
                config.log(f"purge background failed: {exc}")

    # ---- 素材清理（P3.8-h 从桥接层搬出） ----

    def _purge_covers(self, game_id: str) -> None:
        for folder in (config.COVER_SOURCE_DIR, config.USER_COVER_DIR):
            try:
                for item in folder.glob(f"{game_id}-*"):
                    if item.is_file():
                        item.unlink()
            except Exception as exc:
                config.log(f"purge cover failed: {exc}")

    def _remove_icon_files(self, game_id: str) -> None:
        for folder in (config.ICON_SOURCE_DIR, config.USER_ICON_DIR):
            try:
                for item in folder.glob(f"{game_id}.*"):
                    item.unlink()
            except Exception:
                pass
