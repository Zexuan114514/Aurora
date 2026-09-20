"""游戏库用例服务（P3.8）：增删改查 / 分类书架 / 状态与收藏 / 素材字段。

方法体从 aurora/ui/bridge/library.py 原样搬出，只把 `self._emit(...)` 改成向默认总线发布
（Api 的通配订阅会把它推给前端）。打开文件对话框的 pick_* 与导入流程仍留在桥接层。
"""
from __future__ import annotations

from aurora.app.events import default_bus
from aurora.app.projection import _public


class LibraryService:
    """游戏库数据用例（不含文件对话框与导入扫描）。"""

    def __init__(self, library, pm) -> None:
        self._library = library
        self._pm = pm

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
            self.apply_window_icon("")
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}
