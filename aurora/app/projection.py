"""前端投影（P3.8 从 aurora/ui/bridge/shared.py 上移）：内部游戏记录 → 前端契约字段。

纯函数；服务层与桥接层共用，避免 app → ui 的反向依赖。
"""
from __future__ import annotations

from pathlib import Path


def _public(game: dict, pm: process.ProcessManager) -> dict:
    exe = Path(game.get("exe", ""))
    play = game.get("play_time", 0)
    running = pm.is_running(game["id"])
    if running:
        play += int(pm.play_seconds(game["id"]))
    return {
        "id": game["id"],
        "name": game.get("name") or exe.stem,
        "exe": str(exe),
        "exe_name": exe.name,
        "dir": str(exe.parent),
        "appid": game.get("appid"),
        "steam_name": game.get("steam_name") or "",
        "description": game.get("description") or "",
        "description_original": game.get("description_original") or "",
        "description_translated": game.get("description_translated") or "",
        "description_lang": game.get("description_lang") or "",
        "about": game.get("about") or "",
        "developers": game.get("developers") or [],
        "publishers": game.get("publishers") or [],
        "genres": game.get("genres") or [],
        "categories": game.get("categories") or [],
        "release_date": game.get("release_date") or "",
        "metacritic": game.get("metacritic"),
        "website": game.get("website") or "",
        "store_url": game.get("store_url") or "",
        "cover": game.get("cover") or "",
        "cover_sources": game.get("cover_sources") or [],
        "custom_cover": game.get("custom_cover") or "",
        "custom_icon": game.get("custom_icon") or "",
        "logo": game.get("logo") or "",
        "header_image": game.get("header_image") or "",
        "images": game.get("images") or [],
        "background": game.get("background") or "",
        "background_kind": game.get("background_kind") or "",
        "bg_scale": float(game.get("bg_scale") or 1.0),
        "bg_x": float(game.get("bg_x") or 0.0),
        "bg_y": float(game.get("bg_y") or 0.0),
        "metadata_state": game.get("metadata_state") or "pending",
        "metadata_note": game.get("metadata_note") or "",
        "query_used": game.get("query_used") or "",
        "match_score": game.get("match_score"),
        "match_source": game.get("match_source") or "",
        "data_source": game.get("data_source") or "",
        "source_url": game.get("source_url") or "",
        "source_id": game.get("source_id") or "",
        "name_cn": game.get("name_cn") or "",
        "name_original": game.get("name_original") or "",
        "name_locked": bool(game.get("name_locked")),
        "rating": game.get("rating") or "",
        "candidates": game.get("candidates") or [],
        "queries": game.get("queries") or [],
        "strong_queries": game.get("strong_queries") or [],
        "running": running,
        "session_started_at": int(pm.started_at(game["id"])) if running else 0,
        "play_pid": int(game.get("play_pid") or 0) if running else 0,
        "play_time": int(play),
        "play_count": int(game.get("play_count") or 0),
        "sessions": (game.get("sessions") or [])[-5:],
        "last_played": game.get("last_played", 0),
        "favorite": bool(game.get("favorite")),
        "missing": not exe.exists(),
        "launch_args": game.get("launch_args") or "",
        "locale_enabled": bool(game.get("locale_enabled")),
        "locale_guid": game.get("locale_guid") or "",
        "bookshelf_ids": list(game.get("bookshelf_ids") or []),
        "status": game.get("status") or "",
        "vntext_ocr_region": dict(game.get("vntext_ocr_region") or {}),
        "vntext_hook": str(game.get("vntext_hook") or ""),
    }

