"""暴露给前端的 JS 桥接 API。"""
from __future__ import annotations

import os
import json
import queue
import shutil
import threading
import difflib
import time
import uuid
from pathlib import Path

import webview

from . import (config, detect, downloads, gameinput, hookfinder, hotkey, linetrans, locale,
               netproxy, ocr, overlay, process, screencap, steamlib, translate, vntext,
               winapi)
from .sources import SourceManager
from .store import Library

from aurora.domain import session_rules

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
#: 可以直接启动的文件类型（.bat/.cmd 会经 cmd.exe 拉起，见 gl/process.py）
LAUNCHABLE_EXTS = (".exe", ".bat", ".cmd")

NOTES = {
    "network": "网络请求失败，请检查网络后重试",
    "no-results": "所有资料源里都没有找到对应条目",
    "low-confidence": "匹配置信度不足，请手动选择",
    "no-query": "文件名信息太少，请手动搜索确认",
}


def _resolve_note(reason: str | None) -> str:
    return NOTES.get(reason or "", "未找到匹配的商店条目")


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


from aurora.ui.bridge.shell import ShellBridgeMixin
from aurora.ui.bridge.window import WindowBridgeMixin


class Api(WindowBridgeMixin, ShellBridgeMixin):
    def __init__(self) -> None:
        self._library = Library()
        self._pm = process.ProcessManager()
        self._sources = SourceManager(self._library)
        self._window: webview.Window | None = None
        self._drag: dict | None = None
        self._busy: set[str] = set()
        self._lock = threading.RLock()
        self._heartbeat: threading.Thread | None = None
        self._batching = False
        # 简介翻译：单条常驻队列线程串行处理，避免批量导入时线程爆炸
        self._translating: set[str] = set()
        self._trans_queue: "queue.Queue[str]" = queue.Queue()
        self._trans_worker_started = False
        self._tray = None          # 由 main.py 注入托盘控制器（可选）
        # 获取游戏：盯着下载目录，出现新游戏就自动导入
        self._downloads = downloads.DownloadWatcher(
            settings_getter=lambda: self._library.settings,
            save_setting=self._library.set_setting,
            import_fn=lambda paths: len(self.import_dropped(paths).get("games") or []),
            status_fn=lambda payload: self._emit("downloads:status", payload),
        )
        self._downloads.start()
        # 网络：让 gl.sources.net 知道当前用哪条代理路线
        netproxy.set_settings_provider(lambda: self._library.settings)
        self._pm.set_callbacks(on_found=self._on_game_found, on_exit=self._on_game_exit)
        # 游戏内翻译：文本源 / 逐句翻译 / 悬浮窗 / 全局热键
        self._vn_engine = vntext.VnTextEngine(
            settings_getter=lambda: self._library.settings,
            on_line=self._on_vntext_line,
            on_status=lambda state: self._emit("vntext:status", state))
        self._translator = linetrans.LineTranslator(
            settings_getter=lambda: self._library.settings,
            on_event=self._on_translate_event)
        self._overlay = overlay.Overlay(
            get_settings=lambda: self._library.settings,
            set_option=self._library.set_setting,
            on_action=self._on_overlay_action)
        self._hotkeys = hotkey.Hotkeys()
        # 自研钩子查找器（找不到文本时用户手动触发；会话状态给界面轮询）
        self._hooksearch: dict = {"phase": "idle", "message": "", "target": "",
                                  "candidates": [], "code": "", "error": "",
                                  "reason": "", "steps": 0}
        self._hooksearch_stop = threading.Event()
        self._hooksearch_thread: threading.Thread | None = None
        self._hooksearch_lock = threading.RLock()
        self._hotkeys.bind(1, hotkey.MOD_CONTROL | hotkey.MOD_ALT, 0x54,   # Ctrl+Alt+T
                           self._toggle_overlay_click_through)
        self._hotkeys.bind(2, hotkey.MOD_CONTROL | hotkey.MOD_ALT, 0x59,   # Ctrl+Alt+Y
                           self._toggle_overlay_visible)
        # 主热键被别的软件占用时的备选（Ctrl+Shift+F9 / Ctrl+Shift+F10）
        self._hotkeys.bind(3, hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0x78,
                           self._toggle_overlay_click_through)
        self._hotkeys.bind(4, hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0x79,
                           self._toggle_overlay_visible)
        self._recover_sessions()

    # ------------------------------------------------------------------ #
    # 基础
    # ------------------------------------------------------------------ #
    def bootstrap(self) -> dict:
        games = [_public(g, self._pm) for g in self._library.all()]
        return {
            "version": config.VERSION,
            "games": games,
            "settings": dict(self._library.settings),
            "sources": self._sources.describe(),
            "data_dir": str(config.DATA_DIR),
            "platform": os.name,
        }

    def set_setting(self, key: str, value) -> dict:
        return self._library.set_setting(key, value)

    # ------------------------------------------------------------------ #
    # 资料源管理
    # ------------------------------------------------------------------ #
    def list_sources(self) -> list[dict]:
        return self._sources.describe()

    def toggle_source(self, source_id: str, enabled: bool) -> dict:
        self._sources.set_enabled(source_id, bool(enabled))
        return {"ok": True, "sources": self._sources.describe()}

    def move_source(self, source_id: str, delta: int) -> dict:
        self._sources.move(source_id, int(delta))
        return {"ok": True, "sources": self._sources.describe()}

    def add_custom_source(self, config_json: dict) -> dict:
        entry = self._sources.add_custom(config_json or {})
        return {"ok": True, "source": entry, "sources": self._sources.describe()}

    def remove_custom_source(self, source_id: str) -> dict:
        ok = self._sources.remove_custom(source_id)
        return {"ok": ok, "sources": self._sources.describe()}

    def set_merge_sources(self, enabled: bool) -> dict:
        cfg = self._sources.config()
        cfg["merge_images"] = bool(enabled)
        self._sources.save_config(cfg)
        return {"ok": True, "merge_images": cfg["merge_images"]}

    def test_source(self, source_id: str, query: str = "") -> dict:
        return self._sources.test(source_id, query or "千恋万花")

    # ------------------------------------------------------------------ #
    # 获取游戏：Steam 发现 / 一键安装 / 下载目录
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # 获取游戏：资源站（自己增删，点一下用默认浏览器打开）
    # ------------------------------------------------------------------ #
    def _sites(self) -> list[dict]:
        raw = self._library.settings.get("resource_sites")
        rows = raw if isinstance(raw, list) else []
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()[:40]
            url = str(row.get("url") or "").strip()
            if not name or not url.startswith(("http://", "https://")):
                continue
            out.append({"id": str(row.get("id") or f"site{len(out):02d}"),
                        "name": name, "url": url[:500]})
        return out

    def list_sites(self) -> dict:
        return {"ok": True, "sites": self._sites()}

    def add_site(self, name: str, url: str) -> dict:
        """添加一个资源站；地址里可以带 {query} 占位符。"""
        name = (name or "").strip()[:40]
        url = (url or "").strip()
        if not name:
            return {"ok": False, "error": "empty-name"}
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "bad-url"}
        sites = self._sites()
        entry = {"id": f"site{uuid.uuid4().hex[:8]}", "name": name, "url": url[:500]}
        sites.append(entry)
        self._library.set_setting("resource_sites", sites)
        config.log(f"resource site added: {name} {url}")
        return {"ok": True, "site": entry, "sites": sites}

    def remove_site(self, site_id: str) -> dict:
        sites = [row for row in self._sites() if row["id"] != site_id]
        self._library.set_setting("resource_sites", sites)
        return {"ok": True, "sites": sites}

    def get_download_settings(self) -> dict:
        """下载目录 / 监听开关 / 解压开关 / 本机解压器。"""
        return {"ok": True, **self._downloads.status()}

    def set_download_option(self, key: str, value) -> dict:
        """改下载相关设置（目录 / 监听 / 解压）。"""
        if key not in ("download_dir", "download_watch", "download_extract"):
            return {"ok": False, "error": "bad-key"}
        if key == "download_dir":
            path = str(value or "").strip()
            if not path:
                return {"ok": False, "error": "empty"}
            target = Path(path)
            try:
                target.mkdir(parents=True, exist_ok=True)
                probe = target / ".write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self._library.set_setting("download_dir", str(target))
            # 换了目录：清掉旧的“已处理”记录，让新目录重新建基线
            self._library.set_setting("download_baseline_dir", "")
            self._library.set_setting("download_seen", [])
        else:
            self._library.set_setting(key, bool(value))
        return {"ok": True, **self._downloads.status()}

    def scan_downloads(self) -> dict:
        """手动扫一遍下载目录（忽略“已处理”记录）。"""
        res = self._downloads.scan_now()
        if res.get("handled"):
            self._emit("downloads:status", {
                "kind": "imported", "names": res["handled"][:6],
                "count": res.get("imported") or 0,
            })
        return {"ok": bool(res.get("ok")), **res}

    # ------------------------------------------------------------------ #
    # 转区启动（Locale Emulator）
    # ------------------------------------------------------------------ #
    def get_locale_status(self) -> dict:
        settings = self._library.settings
        state = locale.status(str(settings.get("le_proc_path") or ""))
        state["ok"] = True
        state["default_enabled"] = bool(settings.get("locale_default"))
        return state

    def set_locale_option(self, key: str, value) -> dict:
        if key == "locale_default":
            self._library.set_setting("locale_default", bool(value))
        elif key == "le_proc_path":
            path = str(value or "").strip()
            if path:
                ok, err = locale.validate(path)
                if not ok:
                    return {"ok": False, "error": err}
            self._library.set_setting("le_proc_path", path)
        else:
            return {"ok": False, "error": "bad-key"}
        return self.get_locale_status()

    def set_game_locale(self, game_id: str, enabled: bool, guid: str = "") -> dict:
        """单个游戏的转区开关与配置。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        updated = self._library.update(game_id, locale_enabled=bool(enabled),
                                       locale_guid=str(guid or "").strip())
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    # ------------------------------------------------------------------ #
    # 网络：代理状态与连通性
    # ------------------------------------------------------------------ #
    def get_network_status(self) -> dict:
        return netproxy.describe()

    def set_proxy_option(self, key: str, value) -> dict:
        if key == "proxy_mode":
            mode = str(value or "auto").lower()
            if mode not in ("auto", "direct", "manual"):
                return {"ok": False, "error": "bad-mode"}
            self._library.set_setting("proxy_mode", mode)
        elif key == "proxy_url":
            url = str(value or "").strip()
            if url and not netproxy._normalize(url):
                return {"ok": False, "error": "bad-url"}
            self._library.set_setting("proxy_url", url)
        elif key == "proxy_fallback":
            self._library.set_setting("proxy_fallback", bool(value))
        else:
            return {"ok": False, "error": "bad-key"}
        return netproxy.describe()

    def test_network(self) -> dict:
        """逐个试一下关键端点，把「连不上」变成看得见的结果。"""
        from .sources import net

        probes = (
            ("Steam 商店", "https://store.steampowered.com/api/storesearch/?term=neko&cc=CN&l=schinese",
             "GET", None),
            ("Steam 图片", "https://cdn.cloudflare.steamstatic.com/steam/apps/1245620/library_hero.jpg",
             "GET", None),
            ("VNDB", "https://api.vndb.org/kana/vn", "POST",
             {"filters": ["search", "=", "eden"], "fields": "id", "results": 1}),
            ("Bangumi", "https://api.bgm.tv/search/subject/eden?type=4&responseGroup=small",
             "GET", None),
            ("翻译接口", "https://api.mymemory.translated.net/get?q=hello&langpair=en%7Czh-CN",
             "GET", None),
        )
        results = []
        for name, url, method, body in probes:
            started = time.time()
            try:
                payload = json.dumps(body).encode("utf-8") if body else None
                headers = {"Content-Type": "application/json"} if body else None
                net.fetch(url, method=method, body=payload, headers=headers,
                          timeout=10, attempts=1)
                results.append({"name": name, "ok": True,
                                "detail": f"{int((time.time() - started) * 1000)} ms"})
            except Exception as exc:
                results.append({"name": name, "ok": False,
                                "detail": f"{type(exc).__name__}: {str(exc)[:70]}"})
        route = netproxy.current()
        return {"ok": True, "proxy": route["proxy"], "source": route["source"],
                "results": results}

    # ------------------------------------------------------------------ #
    # 游戏内翻译（Textractor 钩子 + 屏幕 OCR）
    # ------------------------------------------------------------------ #
    def _vntext_state(self) -> dict:
        settings = self._library.settings
        cli = vntext.find_cli(str(settings.get("vntext_tractor_path") or ""))
        state = self._vn_engine.status()
        state.update({
            "enabled": bool(settings.get("vntext_enabled")),
            "mode": str(settings.get("vntext_engine") or "auto"),
            "auto_start": bool(settings.get("vntext_auto_start")),
            "tractor": {"found": bool(cli), "path": cli, "url": vntext.TEXTRACTOR_URL,
                        "saved": str(settings.get("vntext_tractor_path") or "")},
            "ocr": ocr.status("ja-JP"),
            "overlay": dict(settings.get("vntext_overlay") or {}),
            "overlay_open": self._overlay.visible(),
            "hotkeys": self._hotkeys.status(),
            "paused": self._translator.paused(),
            "llm_ready": bool(str(settings.get("translate_api_key") or "").strip()),
            "context_lines": int(settings.get("vntext_context_lines") or 4),
            "history": self._translator.history(10),
            # 每游戏专用钩子码（WillPlus 这类 Textractor 自带钩子搞不定的引擎）
            "hook_code": str(state.get("hook_code") or ""),
            "hook_auto": str(state.get("hook_auto") or ""),
            "game_hook": str((self._library.get(str(state.get("game_id") or "")) or {})
                             .get("vntext_hook") or ""),
            "game_locale": bool((self._library.get(str(state.get("game_id") or "")) or {})
                                .get("locale_enabled")),
        })
        return state

    def get_vntext_status(self) -> dict:
        return self._vntext_state()

    def set_vntext_hook(self, game_id: str, code: str) -> dict:
        """给单个游戏存一条专用 hook 码（空串 = 清除，回到自动）。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        text = " ".join(str(code or "").split())
        if text:
            if not vntext.looks_like_hook_code(text):
                return {"ok": False, "error": "bad-code",
                        "hint": "形如 HQ-4@A22E:AdvHD_crack.exe（H + 模式字母 + 偏移 @ 地址 : exe 名）"}
            if ":" not in text:
                # 只给了地址没给模块 → 用游戏自己的 exe 名补上
                text = f"{text}:{Path(str(game.get('exe') or '')).name}"
        self._library.update(game_id, vntext_hook=text)
        if self._vn_engine.status().get("running"):
            self._vn_engine.set_hook_code(text)
        return {"ok": True, "game_id": game_id, "vntext_hook": text,
                **self._vntext_state()}

    def set_vntext_option(self, key: str, value) -> dict:
        allowed = {"vntext_enabled": bool, "vntext_auto_start": bool,
                   "vntext_engine": str, "vntext_context_lines": int,
                   "vntext_max_chars": int, "vntext_ocr_interval": float}
        if key in allowed:
            if key == "vntext_engine" and str(value) not in ("auto", "hook", "ocr"):
                return {"ok": False, "error": "bad-engine"}
            cast = allowed[key]
            try:
                self._library.set_setting(key, cast(value))
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        elif key == "vntext_tractor_path":
            path = str(value or "").strip()
            if path and not Path(path).is_file():
                return {"ok": False, "error": "not-found"}
            self._library.set_setting(key, path)
        elif key == "vntext_overlay":
            patch = dict(self._library.settings.get("vntext_overlay") or {})
            patch.update(value if isinstance(value, dict) else {})
            self._library.set_setting(key, patch)
        else:
            return {"ok": False, "error": "bad-key"}
        return {"ok": True, **self._vntext_state()}

    def start_vntext(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        pid = int(self._pm.game_pid(game_id) or game.get("play_pid") or 0)
        if not pid:
            return {"ok": False, "error": "no-pid"}
        settings = self._library.settings
        region = game.get("vntext_ocr_region") or {}
        self._vn_engine.set_region(region)
        self._library.set_setting("vntext_enabled", True)
        state = self._vn_engine.start(game_id, pid,
                                      str(settings.get("vntext_engine") or "auto"),
                                      exe=str(game.get("exe") or ""),
                                      hook_code=str(game.get("vntext_hook") or ""))
        self._hotkeys.start()
        if state.get("running"):
            self._overlay.show()
            self._overlay.update({"reset": True, "status": "waiting",
                                  "lines": {"source": "", "translation": "",
                                            "status": "waiting"}})
            self._overlay.update({"status": "waiting",
                                  "notice": "" if settings.get("translate_api_key")
                                            else "没填 LLM Key：正在用免费接口，质量与速度较差"})
        self._emit("vntext:status", self._vntext_state())
        return {"ok": bool(state.get("running")), **self._vntext_state()}

    def stop_vntext(self) -> dict:
        self.stop_hook_search()
        self._vn_engine.stop()
        self._overlay.update({"status": "idle"})
        self._overlay.hide()
        if self._library.settings.get("vntext_enabled"):
            self._library.set_setting("vntext_enabled", False)
        self._emit("vntext:status", self._vntext_state())
        return {"ok": True, **self._vntext_state()}

    # ------------------------------------------------------------------ #
    # 自研钩子查找器：OCR 取当前台词 → 内存定位 → 调试器 + 硬件断点 → 生成 H-code → 验证
    # ------------------------------------------------------------------ #
    def _hooksearch_state(self) -> dict:
        with self._hooksearch_lock:
            return dict(self._hooksearch)

    def _set_hooksearch(self, **patch) -> None:
        with self._hooksearch_lock:
            self._hooksearch.update(patch)
            state = dict(self._hooksearch)
        self._emit("hooksearch:status", state)

    def get_hook_search_status(self) -> dict:
        return {"ok": True, **self._hooksearch_state()}

    def advance_game(self, game_id: str) -> dict:
        """代点一下游戏（验证候选钩子码用，也是给用户的手动翻页按钮）。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        pid = int(self._vn_engine.status().get("pid")
                  or self._pm.game_pid(game_id) or 0)
        window = screencap.main_window(pid) if pid else None
        if not window:
            return {"ok": False, "error": "no-window"}
        how = self._hooksearch_advance(int(window["hwnd"]))
        return {"ok": bool(how), "how": how, "error": "" if how else "not-focused"}

    def _hooksearch_advance(self, hwnd: int) -> str:
        """先确保游戏在前台再点（否则 advance 会拒绝发送，游戏永远不会推进）。"""
        try:
            winapi.focus_window(int(hwnd))
            time.sleep(0.25)
        except Exception:
            pass
        return gameinput.advance(int(hwnd))

    def start_hook_search(self, game_id: str, text: str = "") -> dict:
        """开始一次查找（用户点按钮触发；同一时间只允许一个会话）。"""
        if self._hooksearch_thread and self._hooksearch_thread.is_alive():
            return {"ok": False, "error": "busy", **self._hooksearch_state()}
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        status = self._vn_engine.status()
        pid = int(status.get("pid") or self._pm.game_pid(game_id) or 0)
        if not status.get("running") or not pid:
            return {"ok": False, "error": "not-running",
                    "message": "先开启翻译（文本源要挂着才能验证候选码）"}
        window = screencap.main_window(pid)
        if not window:
            return {"ok": False, "error": "no-window", "message": "找不到游戏窗口"}
        self._hooksearch_stop.clear()
        self._set_hooksearch(phase="starting", message="准备中…", target=str(text or ""),
                             candidates=[], code="", error="", reason="", steps=0)
        self._hooksearch_thread = threading.Thread(
            target=self._hooksearch_worker, args=(game_id, pid, int(window["hwnd"]),
                                                  str(text or "")),
            daemon=True, name="aurora-hooksearch")
        self._hooksearch_thread.start()
        return {"ok": True, **self._hooksearch_state()}

    def stop_hook_search(self) -> dict:
        self._hooksearch_stop.set()
        thread = self._hooksearch_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        if self._hooksearch_state().get("phase") not in ("idle", "done", "error"):
            self._set_hooksearch(phase="idle", message="已中止")
        return {"ok": True, **self._hooksearch_state()}

    def _hooksearch_worker(self, game_id: str, pid: int, hwnd: int, text: str) -> None:
        target = " ".join(str(text or "").split())
        try:
            if not target:
                self._set_hooksearch(phase="ocr", message="正在识别画面上的当前台词…")
                shot = screencap.capture({"hwnd": hwnd}, self._vn_engine.status().get("region"))
                if shot.get("ok"):
                    result = ocr.recognize_bgr(shot["bgr"], shot["width"], shot["height"])
                    if result.get("ok"):
                        target = vntext.tidy_ocr_text(result["text"])
            if len(target) < 2:
                target = ""
            # ── 主路径：采样式收集（Misaka「翻页数次后列候选」的思路，不挂钩子）──
            #    采样所有线程栈 → 拿到「返回地址 + 槽偏移 + 那段文本」；
            #    文本能直接读到 → 和 OCR 到的当前台词一比，就知道哪条是原文。
            collected: list[dict] = []
            if True:
                self._set_hooksearch(
                    phase="collecting", target=target,
                    message="正在采样收集候选：Aurora 会翻几页，请别操作游戏")
                clicking = threading.Event()

                def click_loop() -> None:
                    while not clicking.is_set():
                        time.sleep(3.0)
                        if clicking.is_set():
                            break
                        self._hooksearch_advance(hwnd)

                clicker = threading.Thread(target=click_loop, daemon=True,
                                           name="aurora-hooksearch-advance")
                clicker.start()
                try:
                    collected = hookfinder.harvest(
                        pid, seconds=12.0, stop_event=self._hooksearch_stop,
                        on_progress=lambda found, samples: self._set_hooksearch(
                            message=f"已采样 {samples} 次、拿到 {found} 条候选…"))
                finally:
                    clicking.set()
                if self._hooksearch_stop.is_set():
                    return self._set_hooksearch(phase="idle", message="已中止")
                if collected:
                    scored = []
                    for row in collected:
                        score = 0.0
                        if target:
                            score = difflib.SequenceMatcher(
                                None, target, str(row.get("text") or "")).ratio()
                        scored.append((score, row))
                    scored.sort(key=lambda item: (-item[0], -item[1].get("count", 0)))
                    pool = [row for _score, row in scored[:12]]
                    self._set_hooksearch(
                        phase="verifying", steps=len(collected),
                        candidates=[{"code": "", "count": row.get("count", 0),
                                     "encoding": row.get("encoding"),
                                     "sample": str(row.get("text") or "")[:40],
                                     "verified": False} for row in pool],
                        message=f"采到 {len(collected)} 条候选，按「和当前台词像不像」排序…")
                    verified = self._hooksearch_verify_pool(game_id, pid, hwnd, pool,
                                                            target)
                    if verified:
                        return self._set_hooksearch(
                            phase="done", code=verified,
                            message=f"找到了：{verified}（已存为该游戏专用码）")
            # ── 兜底：断点法（差分定位缓冲区 + 硬件数据断点）──
            buffers: list[dict] = []
            if target:
                self._set_hooksearch(phase="scanning", target=target,
                                     message=f"先在内存里找这句文本：{target[:24]}")
                try:
                    # 精确扫描很快（~GB 级内存几秒）；模糊档很慢，留给差分法兜底
                    buffers = hookfinder.locate_buffers(pid, target, allow_fuzzy=False)
                except hookfinder.HookFinderError as exc:
                    if exc.reason == "no-access":
                        raise
                    buffers = []
            if not buffers:
                # 台词常常是渲染时临时生成的（内存里没有逐字副本）→ 改「盯变化」：
                # 拍一张内存哈希快照 → 翻一页 → 找变了的区域里新出现的台词
                self._set_hooksearch(
                    phase="collecting", buffers=0, target=target,
                    message="准备用差分法定位：马上会自动翻一页，请别操作游戏")
                before = hookfinder.snapshot(pid)
                for attempt in range(3):
                    if self._hooksearch_stop.is_set():
                        return self._set_hooksearch(phase="idle", message="已中止")
                    self._hooksearch_advance(hwnd)
                    self._set_hooksearch(
                        message=f"第 {attempt + 1} 次翻页后，正在比对内存变化…")
                    time.sleep(2.0)
                    buffers = hookfinder.changed_dialogues(pid, before)
                    if buffers:
                        target = target or str(buffers[0].get("text") or "")
                        break
                    before = hookfinder.snapshot(pid)
                if not buffers:
                    return self._hooksearch_fail(
                        "no-buffer", "翻页后没在内存里看到新台词 —— 确认游戏停在对话画面再试")
            self._set_hooksearch(
                phase="collecting", buffers=len(buffers),
                message="已布下断点，正在等你翻页（期间 Aurora 会自动帮你点几下）")
            clicking = threading.Event()

            def click_loop() -> None:
                while not clicking.is_set():
                    time.sleep(2.5)
                    if clicking.is_set():
                        break
                    self._hooksearch_advance(hwnd)

            clicker = threading.Thread(target=click_loop, daemon=True,
                                       name="aurora-hooksearch-advance")
            clicker.start()
            found: dict = {"ok": False, "hits": [], "reason": "no-break"}
            try:
                # 每轮：先按「当前这句」重新定位一次（缓冲区可能换地址），再挂断点；
                # 一共给 3 轮机会，期间 Aurora 自己翻页制造访问。
                for round_no in range(3):
                    if self._hooksearch_stop.is_set():
                        break
                    if round_no and not buffers:
                        buffers = hookfinder.changed_dialogues(pid, before)
                    found = hookfinder.search(pid, buffers, seconds=6.0,
                                              stop_event=self._hooksearch_stop,
                                              on_hit=self._hooksearch_on_hit)
                    if found.get("ok"):
                        break
                    before = hookfinder.snapshot(pid)
                    self._hooksearch_advance(hwnd)
                    time.sleep(1.5)
                    fresh = hookfinder.changed_dialogues(pid, before)
                    if fresh:
                        buffers = fresh
                    if round_no < 2:
                        self._set_hooksearch(
                            message=f"第 {round_no + 2}/3 轮：重新定位当前台词后继续…")
            finally:
                clicking.set()
            if self._hooksearch_stop.is_set():
                return self._set_hooksearch(phase="idle", message="已中止")
            if not found.get("ok"):
                reason = str(found.get("reason") or "")
                if reason == "attach-failed":
                    return self._hooksearch_fail(
                        "attach-failed", "附加调试器失败（游戏可能在反调试/权限更高），改用 OCR 吧")
                if reason == "no-break":
                    return self._hooksearch_fail(
                        "no-break", "断点没被触发：确认台词确实推进过一次再试")
                return self._hooksearch_fail(
                    "no-hit", "抓到了访问，但栈上没留指针（这条文本只走寄存器），改用 OCR 吧")
            candidates: list[dict] = []
            for hit in found.get("hits", [])[:6]:
                module, base = hookfinder.module_of(pid, int(hit["rip"]))
                if not module:
                    continue
                try:
                    code = hookfinder.build_code(
                        module=module, module_base=base, rip=int(hit["rip"]),
                        offset=int(hit["offset"]), padding=int(hit["padding"]),
                        encoding=str(hit.get("encoding") or "utf-16"))
                except hookfinder.HookFinderError:
                    continue
                candidates.append({"code": code, "count": int(hit.get("count") or 0),
                                   "encoding": hit.get("encoding"), "verified": False})
            if not candidates:
                return self._hooksearch_fail("no-candidate", "候选都没落在模块里，改用 OCR 吧")
            self._set_hooksearch(phase="verifying", candidates=candidates,
                                 steps=int(found.get("steps") or 0),
                                 message=f"有 {len(candidates)} 个候选，逐个验证…")
            for index, row in enumerate(candidates):
                if self._hooksearch_stop.is_set():
                    return self._set_hooksearch(phase="idle", message="已中止")
                self._set_hooksearch(
                    message=f"正在验证第 {index + 1}/{len(candidates)} 个候选：{row['code']}")
                if self._hooksearch_try(game_id, hwnd, row["code"], target):
                    row["verified"] = True
                    self._set_hooksearch(phase="done", code=row["code"], candidates=candidates,
                                         message=f"找到了：{row['code']}（已存为该游戏专用码）")
                    return
            return self._hooksearch_fail("all-failed", "候选都验证失败，改用 OCR 吧")
        except hookfinder.HookFinderError as exc:
            return self._hooksearch_fail(exc.reason, exc.message)
        except Exception as exc:
            config.log(f"hooksearch failed: {exc}")
            return self._hooksearch_fail("error", f"查找出错：{exc}")

    def _hooksearch_on_hit(self, row: dict) -> None:
        self._set_hooksearch(message=f"已捕获访问（第 {row.get('count')} 次）：{hex(int(row.get('rip') or 0))}")

    def _hooksearch_verify_pool(self, game_id: str, pid: int, hwnd: int,
                                pool: list[dict], target: str) -> str:
        """把采样来的候选变成 H-code 逐个验证，返回第一个能出真台词的码。"""
        tried = 0
        for row in pool:
            if self._hooksearch_stop.is_set():
                return ""
            module, base = hookfinder.module_of(pid, int(row.get("rip") or 0))
            if not module:
                continue
            try:
                code = hookfinder.build_code(
                    module=module, module_base=base, rip=int(row["rip"]),
                    offset=int(row["offset"]), padding=int(row.get("padding") or 0),
                    encoding=str(row.get("encoding") or "utf-16"))
            except hookfinder.HookFinderError:
                continue
            tried += 1
            if tried > 8:
                break
            self._set_hooksearch(
                message=f"验证第 {tried} 个候选：{code}"
                        f"（采样到：{str(row.get('text') or '')[:20]}）")
            if self._hooksearch_try(game_id, hwnd, code, target):
                return code
        return ""

    def _hooksearch_fail(self, reason: str, message: str) -> None:
        config.log(f"hooksearch: {reason} {message}")
        self._set_hooksearch(phase="error", error=reason, reason=reason, message=message)

    def _hooksearch_try(self, game_id: str, hwnd: int, code: str, target: str) -> bool:
        """发一条候选码 → 代点翻页 → 看这条线程有没有吐出像样的台词。"""
        before = self._hooksearch_sample(code)
        if not self._vn_engine.send_hook(code).get("ok"):
            return False
        for _ in range(3):
            if self._hooksearch_stop.is_set():
                return False
            self._hooksearch_advance(hwnd)
            deadline = time.time() + 5.0
            while time.time() < deadline and not self._hooksearch_stop.is_set():
                time.sleep(0.4)
                sample = self._hooksearch_sample(code)
                if sample and sample != before:
                    if vntext.looks_like_dialogue(sample) or \
                            difflib.SequenceMatcher(None, target, sample).ratio() >= 0.6:
                        self._library.update(game_id, vntext_hook=code)
                        self._vn_engine.set_hook_code(code)
                        return True
        return False

    def _hooksearch_sample(self, code: str) -> str:
        status = self._vn_engine.status()
        for row in status.get("threads") or []:
            if vntext.hook_code_matches(code, f"{row.get('name','')}:{row.get('code','')}"):
                return str(row.get("sample") or "")
        return ""

    def close_overlay(self) -> dict:
        """主窗口关闭时把悬浮窗一起收掉。"""
        try:
            self._hotkeys.stop()
        except Exception:
            pass
        return self._overlay.close()

    def shutdown(self) -> None:
        """应用退出前的收尾：停文本会话与下载监听 → 落盘 → 关停存储写线程。"""
        for name, action in (("vntext", self.stop_vntext),
                             ("downloads", self._downloads.stop)):
            try:
                action()
            except Exception as exc:
                config.log(f"{name} shutdown failed: {exc}")
        try:
            self._library.close()
        except Exception as exc:
            config.log(f"store shutdown failed: {exc}")

    def set_vntext_region(self, game_id: str, region: dict) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        clean = {
            "x": max(0.0, min(1.0, float((region or {}).get("x", 0.0)))),
            "y": max(0.0, min(1.0, float((region or {}).get("y", 0.62)))),
            "w": max(0.02, min(1.0, float((region or {}).get("w", 1.0)))),
            "h": max(0.02, min(1.0, float((region or {}).get("h", 0.34)))),
        }
        self._library.update(game_id, vntext_ocr_region=clean)
        self._vn_engine.set_region(clean)
        return {"ok": True, "region": clean}

    def capture_game_frame(self, game_id: str) -> dict:
        """截一张游戏窗口的图，供界面里框选 OCR 区域。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        pid = int(self._pm.game_pid(game_id) or game.get("play_pid") or 0)
        window = screencap.main_window(pid) if pid else None
        if not window:
            return {"ok": False, "error": "no-window"}
        shot = screencap.capture(window)
        if not shot.get("ok"):
            return {"ok": False, "error": shot.get("error") or "capture-failed"}
        name = f"vntext-{game_id}.png"
        target = config.USER_BG_DIR / name
        try:
            config.USER_BG_DIR.mkdir(parents=True, exist_ok=True)
            if not screencap.save_png(target, shot["bgr"], shot["width"], shot["height"]):
                return {"ok": False, "error": "no-pillow"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "url": f"userbg/{name}?v={int(time.time())}",
                "width": shot["width"], "height": shot["height"],
                "region": dict(game.get("vntext_ocr_region") or {})}

    def lock_vntext_thread(self, key: str) -> dict:
        self._vn_engine.lock_thread(key)
        return {"ok": True, **self._vntext_state()}

    def send_hook_code(self, code: str) -> dict:
        result = self._vn_engine.send_hook(code)
        return {**result, **self._vntext_state()}

    def translate_line_now(self, text: str) -> dict:
        text = str(text or "").strip()
        if not text:
            return {"ok": False, "error": "empty"}
        game_id = str(self._vn_engine.status().get("game_id") or "")
        self._overlay.show()
        self._translator.submit(text, game_id=game_id, source="manual")
        return {"ok": True}

    def set_vntext_paused(self, paused: bool) -> dict:
        self._translator.set_paused(bool(paused))
        self._overlay.update({"paused": self._translator.paused()})
        return {"ok": True, "paused": self._translator.paused()}

    def clear_vntext_context(self) -> dict:
        return self._translator.clear_context()

    def set_overlay_style(self, patch: dict) -> dict:
        return self._overlay.set_style(patch if isinstance(patch, dict) else {})

    def set_overlay_click_through(self, on: bool) -> dict:
        return self._overlay.set_click_through(bool(on))

    def toggle_overlay(self) -> dict:
        return self._toggle_overlay_visible()

    def list_glossary(self) -> dict:
        data = linetrans.load_glossary()
        return {"ok": True, "global": data.get("global") or {},
                "games": data.get("games") or {}}

    def set_glossary_entry(self, source: str, target: str, game_id: str = "") -> dict:
        source = str(source or "").strip()
        target = str(target or "").strip()
        if not source:
            return {"ok": False, "error": "empty-source"}
        data = linetrans.load_glossary()
        if game_id:
            bucket = data.setdefault("games", {}).setdefault(str(game_id), {})
        else:
            bucket = data.setdefault("global", {})
        if target:
            bucket[source] = target
        else:
            bucket.pop(source, None)
        data["version"] = int(data.get("version") or 1) + 1
        linetrans.save_glossary(data)
        return {"ok": True, **self.list_glossary()}

    def remove_glossary_entry(self, source: str, game_id: str = "") -> dict:
        return self.set_glossary_entry(source, "", game_id)

    # ------------------------------------------------------------------ #
    def _on_vntext_line(self, payload: dict) -> None:
        text = str(payload.get("text") or "")
        game_id = str(payload.get("game_id") or "")
        self._translator.submit(text, game_id=game_id, source=str(payload.get("source") or ""))
        self._emit("vntext:line", {"phase": "source", "text": text,
                                   "source": payload.get("source") or ""})

    def _on_translate_event(self, kind: str, payload: dict) -> None:
        text = str(payload.get("text") or "")
        if kind == "start":
            self._overlay.update({"lines": {"source": text, "translation": "",
                                            "status": "translating"}})
        elif kind == "delta":
            self._overlay.update({"lines": {"translation": payload.get("so_far") or "",
                                            "status": "translating"}})
        elif kind == "done":
            self._overlay.update({"lines": {"source": text,
                                            "translation": payload.get("translation") or "",
                                            "status": "done",
                                            "provider": payload.get("provider") or ""},
                                  "notice": ""})
            self._emit("vntext:line", {"phase": "translated", "text": text,
                                       "translation": payload.get("translation") or "",
                                       "provider": payload.get("provider") or ""})
        elif kind == "error":
            # 失败时保留上一句译文，只提示一句，避免「真文本一闪而过」
            self._overlay.update({"status": "error",
                                  "notice": "这句没翻出来（可能是乱码或网络问题）"})
            self._emit("vntext:line", {"phase": "error", "text": text,
                                       "error": payload.get("error") or ""})

    def _on_overlay_action(self, name: str, payload) -> dict:
        if name == "pause":
            return self.set_vntext_paused(bool(payload))
        if name == "hide":
            self._overlay.hide()
            return {"ok": True}
        if name == "retry":
            return self._translator.retranslate_last()
        if name == "clear_context":
            return self.clear_vntext_context()
        return {"ok": False, "error": "unknown-action"}

    def _toggle_overlay_click_through(self) -> None:
        result = self._overlay.toggle_click_through()
        self._emit("vntext:status", {**self._vntext_state(), "toggled": result})

    def _toggle_overlay_visible(self) -> dict:
        if self._overlay.visible():
            self._overlay.hide()
        else:
            self._overlay.show()
        self._emit("vntext:status", self._vntext_state())
        return {"ok": True, "visible": self._overlay.visible()}

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
        self._emit("games:imported", {
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

    def toggle_favorite(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        updated = self._library.update(game_id, favorite=not bool(game.get("favorite")))
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {
            "ok": bool(updated),
            "favorite": bool(updated.get("favorite")) if updated else False,
            "game": _public(updated, self._pm) if updated else None,
        }

    # ------------------------------------------------------------------ #
    # 分类书架（多对多）与游玩状态
    # ------------------------------------------------------------------ #
    def _shelves_payload(self) -> dict:
        stats = self._library.shelf_counts()
        shelves = []
        for shelf in self._library.shelves():
            shelves.append({**shelf, "count": int(stats["counts"].get(shelf["id"], 0))})
        return {"ok": True, "shelves": shelves, "unfiled": int(stats["unfiled"]),
                "total": int(stats["total"])}

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
        self._emit("game:updated", _public(updated, self._pm))
        return {"ok": True, "game": _public(updated, self._pm)}

    # ------------------------------------------------------------------ #
    # 自定义名称 / 封面
    # ------------------------------------------------------------------ #
    def rename_game(self, game_id: str, name: str) -> dict:
        """手动改名。改过之后重新匹配也不会被覆盖（name_locked）。"""
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "empty"}
        updated = self._library.update(game_id, name=name[:120], name_locked=True)
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    def reset_name(self, game_id: str) -> dict:
        """恢复成自动匹配的名字，并重新搜一次。"""
        updated = self._library.update(game_id, name_locked=False)
        if not updated:
            return {"ok": False}
        self._auto_search_async(game_id)
        return {"ok": True, "game": _public(updated, self._pm)}

    def set_cover(self, game_id: str, url: str) -> dict:
        """把某张图设为封面（url 一般来自该游戏的图片列表）。"""
        updated = self._library.update(game_id, custom_cover=url or "")
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    def clear_custom_cover(self, game_id: str) -> dict:
        self._purge_covers(game_id)
        updated = self._library.update(game_id, custom_cover="")
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    def pick_local_cover(self, game_id: str) -> dict:
        """用本地图片当封面（原图存 data/covers，副本给页面用）。"""
        if self._window is None:
            return {"ok": False}
        if not self._library.get(game_id):
            return {"ok": False, "error": "no-game"}
        result = self._window.create_file_dialog(
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
            shutil.copy2(source, config.USER_COVER_DIR / name)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        url = f"usercovers/{name}"
        updated = self._library.update(game_id, custom_cover=url)
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {"ok": True, "game": _public(updated, self._pm) if updated else None}

    def _purge_covers(self, game_id: str) -> None:
        for folder in (config.COVER_SOURCE_DIR, config.USER_COVER_DIR):
            try:
                for item in folder.glob(f"{game_id}-*"):
                    if item.is_file():
                        item.unlink()
            except Exception as exc:
                config.log(f"purge cover failed: {exc}")

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
        threading.Thread(target=self._refresh_all_worker, args=(ids,),
                         daemon=True, name="aurora-refresh-all").start()
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

    def export_library(self) -> dict:
        """导出游戏库为一份 JSON（换机 / 备份用）。"""
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._window.create_file_dialog(
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
        result = self._window.create_file_dialog(
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

    # ------------------------------------------------------------------ #
    # Steam 库
    # ------------------------------------------------------------------ #
    def scan_steam(self) -> dict:
        """扫描本机 Steam 库，返回可直接导入的游戏列表。"""
        from . import steamlib

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
        threading.Thread(target=self._steam_worker, args=(items,),
                         daemon=True, name="aurora-steam-import").start()
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

    def set_launch_args(self, game_id: str, args: str) -> dict:
        game = self._library.update(game_id, launch_args=args or "")
        return {"ok": bool(game)}

    # ------------------------------------------------------------------ #
    # 元数据搜索
    # ------------------------------------------------------------------ #
    def _auto_search_async(self, game_id: str) -> None:
        threading.Thread(target=self._auto_search, args=(game_id,), daemon=True).start()

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
    def _translate_async(self, game_id: str, force: bool = False) -> None:
        """把翻译任务丢进常驻队列线程。

        force=True 用于用户手动触发（不受「导入后自动翻译」开关限制）。
        """
        if not force and not self._library.settings.get("translate_enabled", True):
            return
        if not self._trans_worker_started:
            self._trans_worker_started = True
            threading.Thread(target=self._translate_queue_loop, daemon=True,
                             name="aurora-translate-q").start()
        self._trans_queue.put((game_id, bool(force)))

    def _translate_queue_loop(self) -> None:
        while True:
            item = self._trans_queue.get()
            game_id, manual = item if isinstance(item, tuple) else (item, False)
            try:
                res = self._translate_description(game_id)
                # 用户手动点的「翻译简介」要有回执，自动翻译保持安静
                if manual:
                    self._emit("translate:done", {"id": game_id, "manual": True, **res})
            except Exception as exc:  # pragma: no cover
                config.log(f"translate queue error: {exc}")
            finally:
                self._trans_queue.task_done()

    def _translate_description(self, game_id: str) -> dict:
        """翻译单个游戏的简介（自动 / 批量 / 手动共用）。"""
        with self._lock:
            if game_id in self._translating:
                return {"ok": False, "changed": False, "error": "busy"}
            self._translating.add(game_id)
        try:
            game = self._library.get(game_id)
            if not game:
                return {"ok": False, "changed": False, "error": "no-game"}
            text = (game.get("description_original") or game.get("description") or "").strip()
            if not text:
                return {"ok": False, "changed": False, "error": "empty"}
            settings = dict(self._library.settings)
            res = translate.translate_text(
                text, target=str(settings.get("translate_target") or translate.TARGET_DEFAULT),
                settings=settings)
            # 陈旧保护：翻译期间若被并发重新抓取换掉了简介，就丢弃这次结果
            current = self._library.get(game_id)
            if not current or (current.get("description_original")
                               or current.get("description") or "").strip() != text:
                return {"ok": False, "changed": False, "error": "stale"}
            fields = {"description_original": text, "description_lang": res["lang"]}
            if res.get("changed"):
                fields["description"] = res["text"]
                fields["description_translated"] = res["text"]
            updated = self._library.update(game_id, **fields)
            if updated:
                self._emit("game:updated", _public(updated, self._pm))
            return {"ok": bool(res.get("changed")), "changed": bool(res.get("changed")),
                    "provider": res.get("provider"), "lang": res.get("lang")}
        finally:
            with self._lock:
                self._translating.discard(game_id)

    def translate_game(self, game_id: str) -> dict:
        """手动翻译单个游戏的简介（不受自动翻译开关限制）。"""
        if not self._library.get(game_id):
            return {"ok": False, "error": "no-game"}
        self._translate_async(game_id, force=True)
        return {"ok": True}

    def translate_all_descriptions(self) -> dict:
        """批量翻译库里所有非中文的简介（后台跑，进度用事件推给前端）。"""
        if self._batching:
            return {"ok": False, "error": "busy"}
        ids = [g["id"] for g in self._library.all()
               if (g.get("description") or g.get("description_original"))]
        if not ids:
            return {"ok": False, "error": "empty"}
        threading.Thread(target=self._translate_all_worker, args=(ids,),
                         daemon=True, name="aurora-translate-all").start()
        return {"ok": True, "total": len(ids)}

    def _translate_all_worker(self, ids: list[str]) -> None:
        self._batching = True
        translated = skipped = failed = 0
        try:
            total = len(ids)
            for index, game_id in enumerate(ids):
                if not self._library.get(game_id):
                    continue
                self._emit("batch:progress",
                           {"done": index, "total": total, "kind": "translate"})
                res = self._translate_description(game_id)
                if res.get("changed"):
                    translated += 1
                elif res.get("error"):
                    failed += 1
                else:
                    skipped += 1
            self._emit("batch:progress",
                       {"done": total, "total": total, "kind": "translate"})
        finally:
            self._batching = False
            self._emit("batch:done", {
                "total": len(ids), "kind": "translate",
                "translated": translated, "skipped": skipped, "failed": failed,
            })

    def test_translation(self, overrides: dict | None = None) -> dict:
        """设置面板的「测试」按钮：实时验证翻译接口是否可用。"""
        settings = dict(self._library.settings)
        if isinstance(overrides, dict):
            settings.update({k: v for k, v in overrides.items() if v is not None})
        return translate.test_provider(settings)

    # ------------------------------------------------------------------ #
    # 背景
    # ------------------------------------------------------------------ #
    def set_background(self, game_id: str, url: str, kind: str = "remote") -> dict:
        game = self._library.update(game_id, background=url, background_kind=kind)
        if game:
            self._emit("game:updated", _public(game, self._pm))
        return {"ok": bool(game), "game": _public(game, self._pm) if game else None}

    def clear_background(self, game_id: str) -> dict:
        game = self._library.update(game_id, background="", background_kind="")
        if game:
            self._emit("game:updated", _public(game, self._pm))
        return {"ok": bool(game), "game": _public(game, self._pm) if game else None}

    def set_background_view(self, game_id: str, scale: float, x: float, y: float) -> dict:
        """保存背景的缩放与平移（仅写入磁盘，不推送事件，避免拖拽时反复重绘）。"""
        game = self._library.update(
            game_id,
            bg_scale=max(1.0, min(float(scale), 4.0)),
            bg_x=float(x),
            bg_y=float(y),
        )
        return {"ok": bool(game)}

    def pick_local_background(self, game_id: str) -> dict:
        if self._window is None:
            return {"ok": False}
        result = self._window.create_file_dialog(
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
            shutil.copy2(source, config.USER_BG_DIR / name)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        url = f"userbg/{name}"
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
        result = self._window.create_file_dialog(
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
            shutil.copy2(source, config.USER_ICON_DIR / name)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        url = f"usericon/{name}?v={int(time.time())}"
        updated = self._library.update(game_id, custom_icon=url)
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
            self.apply_window_icon(game_id)
        return {"ok": True, "game": _public(updated, self._pm) if updated else None}

    def clear_custom_icon(self, game_id: str) -> dict:
        self._remove_icon_files(game_id)
        updated = self._library.update(game_id, custom_icon="")
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
            self.apply_window_icon("")
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}

    def _remove_icon_files(self, game_id: str) -> None:
        for folder in (config.ICON_SOURCE_DIR, config.USER_ICON_DIR):
            try:
                for item in folder.glob(f"{game_id}.*"):
                    item.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # 运行
    # ------------------------------------------------------------------ #
    def launch(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        launcher, locale_note = self._locale_command(game)
        result = self._pm.start(game, launcher=launcher)
        if result.get("ok"):
            now = int(time.time())
            self._library.touch_played(game_id)
            # 落盘会话标记：万一启动器先被关掉，下次启动还能把时长补回来
            self._library.update(
                game_id,
                play_started_at=int(result.get("started_at") or now),
                play_pid=int(result.get("pid") or 0),
                play_launcher_pid=int(result.get("pid") or 0),
                play_heartbeat=now,
                play_count=int(game.get("play_count") or 0) + 1,
            )
            self._start_heartbeat()
            self._emit("game:running", {"id": game_id, "pid": result.get("pid"),
                                        "locale": locale_note})
        return result

    def _locale_command(self, game: dict) -> tuple[list[str] | None, str]:
        """按游戏的转区设置决定启动方式；返回 (启动命令, 说明)。"""
        if not game.get("locale_enabled"):
            return None, ""
        proc = locale.detect(str(self._library.settings.get("le_proc_path") or ""))
        if not proc:
            return None, "no-le"
        exe = str(game.get("exe") or "")
        if Path(exe).suffix.lower() != ".exe":
            return None, "unsupported-target"
        guid = str(game.get("locale_guid") or "").strip()
        return locale.build_command(proc, exe, guid=guid), ("locale" if guid else "locale-default")

    def _on_game_found(self, game_id: str, pid: int) -> None:
        """找到游戏本体进程：把它记下来，启动器重启后也能重新接管。"""
        if not game_id or not pid:
            return
        self._library.update(game_id, play_pid=int(pid))
        # 开了「启动游戏自动翻译」就顺手接上文本源
        settings = self._library.settings
        if settings.get("vntext_auto_start") or settings.get("vntext_enabled"):
            try:
                self.start_vntext(game_id)
            except Exception as exc:
                config.log(f"vntext auto start failed: {exc}")

    def _on_game_exit(self, game_id: str, seconds: float) -> None:
        """会话结束：结算时长、记一条会话历史、清掉会话标记。"""
        try:
            if self._vn_engine.status().get("game_id") == game_id:
                self.stop_vntext()
        except Exception as exc:
            config.log(f"vntext auto stop failed: {exc}")
        game = self._library.get(game_id)
        if not game:
            return
        now = int(time.time())
        started = int(game.get("play_started_at") or 0) or int(now - seconds)
        self._library.update(
            game_id,
            play_started_at=0, play_pid=0, play_launcher_pid=0, play_heartbeat=0,
        )
        # 会话历史：内存保留最近 50 条 + 追加进 state/sessions.jsonl（立即落盘）
        self._library.record_session(game_id, {"ts_start": started, "ts_end": now,
                                               "seconds": int(seconds), "source": "session"})
        self._library.touch_played(game_id, seconds)
        updated = self._library.get(game_id)
        if updated:
            self._emit("game:stopped", _public(updated, self._pm))

    def stop(self, game_id: str) -> dict:
        result = self._pm.stop(game_id)
        game = self._library.get(game_id)
        if game:
            self._emit("game:updated", _public(game, self._pm))
        return result

    #: 运行中每隔多少秒把「还活着」写一次盘（用于崩溃/被强关时估算时长）
    HEARTBEAT_SECONDS = 30

    def _start_heartbeat(self) -> None:
        if self._heartbeat is not None and self._heartbeat.is_alive():
            return

        def loop() -> None:
            while True:
                time.sleep(self.HEARTBEAT_SECONDS)
                try:
                    self._beat()
                except Exception:
                    pass

        thread = threading.Thread(target=loop, daemon=True, name="aurora-heartbeat")
        self._heartbeat = thread
        thread.start()

    def _beat(self) -> None:
        now = int(time.time())
        for game_id in self._pm.running_ids():
            self._library.update(game_id, play_heartbeat=now)

    def _recover_sessions(self) -> None:
        """启动时对账上次没结束的会话。

        游戏还在跑就重新接管（界面照常显示「运行中」、退出时照常累计），
        已经结束的按最后一个心跳补记时长，避免「先关启动器再关游戏」丢时长。
        """
        now = int(time.time())
        for game in self._library.all():
            started = int(game.get("play_started_at") or 0)
            if started <= 0:
                continue
            if self._pm.attach(game, started):
                # 接管后由 ProcessManager 自己的监控线程负责判定结束并回调
                # _on_game_exit（旧实现这里调用已删除的 self._watch，会启动即崩）
                config.log(f"reattached running game {game['id']} pid={game.get('play_pid')}")
                self._start_heartbeat()
                continue
            seconds = session_rules.recovered_seconds(
                started_at=started, heartbeat=game.get("play_heartbeat") or 0, now=now)
            self._library.update(game["id"], play_started_at=0, play_pid=0,
                                 play_launcher_pid=0, play_heartbeat=0)
            if session_rules.is_countable(seconds, self.HEARTBEAT_SECONDS):
                self._library.touch_played(game["id"], seconds)
                config.log(f"recovered {seconds}s playtime for {game['id']}")

    def refresh_running(self) -> dict:
        return {"running": self._pm.running_ids()}

    # ------------------------------------------------------------------ #
    def _emit(self, event: str, payload: dict) -> None:
        """把事件推送给前端。"""
        if self._window is None:
            return
        import json

        try:
            self._window.evaluate_js(
                f"window.__aurora && window.__aurora.emit({json.dumps(event)},"
                f"{json.dumps(payload, ensure_ascii=False)})"
            )
        except Exception as exc:
            config.log(f"emit failed {event}: {exc}")
