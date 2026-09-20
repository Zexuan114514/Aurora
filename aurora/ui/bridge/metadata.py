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
        """把库里所有游戏重新抓一遍资料（后台跑，进度用事件推给前端）。"""
        if self._batching:
            return {"ok": False, "error": "busy"}
        ids = [g["id"] for g in self._library.all()]
        if not ids:
            return {"ok": False, "error": "empty"}
        self._tasks.spawn("metadata.refresh_all", self._refresh_all_worker, ids,
                               thread_name="aurora-refresh-all")
        return {"ok": True, "total": len(ids)}


    def _refresh_all_worker(self, ids: list[str]) -> None:
        self._batching = True
        try:
            total = len(ids)
            for index, game_id in enumerate(ids):
                if not self._library.get(game_id):
                    continue
                self._emit("batch:progress", {"done": index, "total": total})
                self._auto_search(game_id)
            self._emit("batch:progress", {"done": total, "total": total})
        finally:
            self._batching = False
            self._emit("batch:done", {"total": len(ids)})


    # ------------------------------------------------------------------ #
    # Steam 库
    # ------------------------------------------------------------------ #
    def scan_steam(self) -> dict:
        """扫描本机 Steam 库，返回可直接导入的游戏列表。"""
        from gl import steamlib

        existing = {str(g.get("exe") or "") for g in self._library.all()}
        try:
            return steamlib.scan(existing)
        except Exception as exc:
            config.log(f"steam scan failed: {exc}")
            return {"ok": False, "error": str(exc), "games": []}


    def import_steam_games(self, items: list[dict]) -> dict:
        """导入选中的 Steam 游戏；有 appid 的直接按 appid 取资料。"""
        items = [row for row in (items or []) if isinstance(row, dict) and row.get("exe")]
        if not items:
            return {"ok": False, "error": "empty"}
        self._tasks.spawn("metadata.steam_import", self._steam_worker, items,
                               thread_name="aurora-steam-import")
        return {"ok": True, "total": len(items)}


    def _steam_worker(self, items: list[dict]) -> None:
        self._batching = True
        imported: list[dict] = []
        try:
            total = len(items)
            for index, item in enumerate(items):
                self._emit("batch:progress", {"done": index, "total": total})
                game = self._import_one(str(item["exe"]), auto_search=False)
                if not game:
                    continue
                imported.append(game)
                appid = item.get("appid")
                if appid and game.get("metadata_state") != "ok":
                    self._apply_source(game["id"], "steam", str(int(appid)),
                                       name=game.get("name", ""), source="steam-scan")
                updated = self._library.get(game["id"])
                if updated and updated.get("metadata_state") != "ok" \
                        and self._library.settings.get("auto_search", True):
                    self._auto_search(game["id"])
            self._emit("batch:progress", {"done": total, "total": total})
        finally:
            self._batching = False
            if imported:
                self._emit("games:imported", {
                    "games": [_public(self._library.get(g["id"]) or g, self._pm)
                              for g in imported],
                    "ids": [g["id"] for g in imported],
                    "ignored": 0,
                })
            self._emit("batch:done", {"total": len(items), "imported": len(imported)})


    # ------------------------------------------------------------------ #
    # 元数据搜索
    # ------------------------------------------------------------------ #
    def _auto_search_async(self, game_id: str) -> None:
        self._tasks.spawn("metadata.auto_search", self._auto_search, game_id,
                               thread_name="aurora-auto-search")


    def _auto_search(self, game_id: str) -> None:
        with self._lock:
            if game_id in self._busy:
                return
            self._busy.add(game_id)
        try:
            game = self._library.get(game_id)
            if not game:
                return
            self._library.update(game_id, metadata_state="searching", metadata_note="")
            self._emit("metadata:searching", {"id": game_id})

            info = detect.describe_path(Path(game["exe"]))
            strong = game.get("strong_queries") or info["strong_queries"]
            queries = strong or game.get("queries") or info["queries"]

            if not strong:
                # 只有 b1 / x64 这类代号，不做自动匹配，交给用户手动选择
                note = "文件名信息太少，请手动搜索确认"
                self._library.update(
                    game_id, metadata_state="notfound", metadata_note=note,
                    queries=queries, strong_queries=[],
                )
                self._emit("metadata:notfound", {
                    "id": game_id, "note": note, "candidates": [],
                    "quiet": self._batching,
                    "game": _public(self._library.get(game_id), self._pm),
                })
                return

            result = self._sources.resolve(queries, threshold=0.75)
            if result.get("ok"):
                self._apply_source(game_id, result["source"], result["source_id"],
                                   name=result.get("name", ""), source="auto",
                                   score=result.get("score"),
                                   query=(result.get("query") or [""])[0])
                return
            note = _resolve_note(result.get("reason"))
            self._library.update(
                game_id,
                metadata_state="notfound",
                metadata_note=note,
                candidates=result.get("candidates") or [],
                queries=queries,
                strong_queries=strong,
            )
            self._emit("metadata:notfound", {
                "id": game_id,
                "note": note,
                "candidates": result.get("candidates") or [],
                "quiet": self._batching,
                "game": _public(self._library.get(game_id), self._pm),
            })
        except Exception as exc:  # pragma: no cover
            config.log(f"auto search error: {exc}")
            self._library.update(game_id, metadata_state="error", metadata_note=str(exc))
            self._emit("metadata:error", {"id": game_id, "note": str(exc)})
        finally:
            with self._lock:
                self._busy.discard(game_id)


    def search(self, game_id: str, query: str | None = None,
               auto_apply: bool = False, all_sources: bool = True) -> dict:
        """按名字搜索。

        默认只返回候选（按匹配度从高到低，最多 20 条）交给候选面板，由用户自己挑，
        不再直接采纳匹配度最高的那条；auto_apply=True 时保留旧行为（自动重搜用）。
        all_sources=True 会把所有启用源都搜一遍，方便在候选里跨源比较。
        """
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        if query:
            queries = [query.strip()]
        else:
            info = detect.describe_path(Path(game["exe"]))
            queries = (game.get("strong_queries") or info["strong_queries"]
                       or game.get("queries") or info["queries"])
        result = self._sources.resolve(queries, threshold=0.75, collect_all=all_sources)
        candidates = result.get("candidates") or []
        if result.get("ok") and auto_apply:
            self._apply_source(game_id, result["source"], result["source_id"],
                               name=result.get("name", ""), source="auto",
                               score=result.get("score"),
                               query=(result.get("query") or [""])[0])
            return {"ok": True, "applied": True,
                    "game": _public(self._library.get(game_id), self._pm)}
        # 只列候选，不动库里的记录：否则会把已经匹配好的游戏标成「没找到」，
        # 封面上多一个 ? 徽标；真正的状态变更留给 apply_candidate。
        return {
            "ok": bool(candidates),
            "applied": False,
            "reason": result.get("reason") or ("ok" if candidates else "no-results"),
            "candidates": candidates,
            "count": len(candidates),
            "best": candidates[0] if candidates else None,
            "queries": queries[:2],
            "game": _public(self._library.get(game_id), self._pm),
        }


    def apply_candidate(self, game_id: str, source_id: str, candidate_id: str,
                        name: str = "", kind: str = "manual") -> dict:
        """用户在候选面板里手动选中某个条目。"""
        self._apply_source(game_id, source_id, candidate_id, name=name, source=kind)
        game = self._library.get(game_id)
        return {"ok": bool(game), "game": _public(game, self._pm) if game else None}


    def apply_appid(self, game_id: str, appid: int, source: str = "manual") -> dict:
        """兼容旧接口：按 Steam appid 应用。"""
        return self.apply_candidate(game_id, "steam", str(appid), kind=source)


    def _apply_source(self, game_id: str, source_id: str, candidate_id: str,
                      name: str = "", source: str = "auto",
                      score: float | None = None, query: str = "") -> None:
        lang = self._library.settings.get("lang", "schinese")
        game = self._library.get(game_id)
        if not game:
            return
        data = self._sources.build(source_id, candidate_id, name=name or game.get("name", ""),
                                   lang=lang)
        if not data:
            self._library.update(game_id, metadata_state="notfound",
                                 metadata_note="该资料源没有返回内容")
            self._emit("metadata:notfound", {
                "id": game_id, "note": "该资料源没有返回内容", "candidates": [],
                "quiet": self._batching,
                "game": _public(self._library.get(game_id), self._pm)})
            return

        images = data.get("images") or []
        # 默认背景：优先官方 hero/封面，其次截图
        current_bg = game.get("background") or ""
        urls = {img["url"] for img in images}
        background = current_bg if current_bg in urls else ""
        kind = game.get("background_kind") if background else ""
        if not background and images:
            background = images[0]["url"]
            kind = images[0]["kind"]

        self._library.update(
            game_id,
            appid=data.get("appid"),
            data_source=source_id,
            source_id=str(candidate_id),
            source_url=data.get("source_url") or "",
            steam_name=data.get("steam_name") or "",
            # 手动改过名字的，重新匹配时保持用户的命名
            name=(game.get("name") if game.get("name_locked")
                  else (data.get("name") or game.get("name"))),
            name_cn=data.get("name_cn") or "",
            name_original=data.get("name_original") or "",
            rating=data.get("rating") or "",
            description=data.get("description") or "",
            # 换了资料源，旧译文作废：否则翻译队列会拿旧原文把新简介覆盖掉
            description_original="",
            description_translated="",
            description_lang="",
            about=data.get("about") or "",
            developers=data.get("developers") or [],
            publishers=data.get("publishers") or [],
            genres=data.get("genres") or [],
            categories=data.get("categories") or [],
            release_date=data.get("release_date") or "",
            metacritic=data.get("metacritic"),
            website=data.get("website") or "",
            store_url=data.get("store_url") or "",
            cover=data.get("cover") or "",
            cover_sources=data.get("cover_sources") or [],
            logo=data.get("logo") or "",
            header_image=data.get("header_image") or "",
            images=images,
            background=background,
            background_kind=kind,
            metadata_state="ok",
            metadata_note="",
            match_source=source,
            match_score=score,
            query_used=query,
        )
        updated = self._library.get(game_id)
        self._emit("game:updated", _public(updated, self._pm))
        # 识别成功后自动翻译简介（异步，不阻塞当前调用）
        self._translate_async(game_id)


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
