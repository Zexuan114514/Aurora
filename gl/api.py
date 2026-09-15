"""暴露给前端的 JS 桥接 API。"""
from __future__ import annotations

import os
import json
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

import webview

from . import config, detect, downloads, locale, netproxy, process, steamlib, translate, winapi
from .sources import SourceManager
from .store import Library

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
        "session_started_at": int(self._pm.started_at(game["id"])) if running else 0,
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
    }


class Api:
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

    def open_source_search(self, query: str, source_id: str = "") -> dict:
        """在指定的“跳转型”源里搜索（用浏览器打开）。"""
        target = None
        for row in self._sources.link_sources():
            if not source_id or row["id"] == source_id:
                target = row
                break
        if target is None:
            return {"ok": False, "error": "no-link-source"}
        source = self._sources.get(target["id"])
        url = source.link_for(query) if source else ""
        if not url:
            return {"ok": False, "error": "no-url"}
        return {**self.open_url(url), "url": url}

    def open_url(self, url: str) -> dict:
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            try:
                os.startfile(url)  # noqa: S606
                return {"ok": True}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "bad-url"}

    def window_cmd(self, command: str) -> dict:
        if self._window is None:
            return {"ok": False}
        if command == "minimize":
            self._window.minimize()
        elif command == "hide":
            self._window.hide()
        elif command == "show":
            self._window.show()
        elif command == "close":
            # 勾了「关闭时缩到托盘」就只藏起来，游戏继续在后台跑
            if self._tray is not None and self._library.settings.get("close_to_tray"):
                self._window.hide()
                self._tray.notify(config.APP_TITLE, "已缩小到托盘，游戏仍在后台运行。")
                return {"ok": True, "hidden": True}
            if self._tray is not None:
                self._tray.stop()
                self._tray = None
            self._window.destroy()
        elif command == "toggle_maximize":
            return {"ok": True, "maximized": winapi.toggle_maximize(self._window)}
        return {"ok": True}

    def set_tray(self, tray) -> None:
        """由 main.py 注入托盘控制器（没有托盘时为 None）。"""
        self._tray = tray

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

    def open_site(self, site_id: str, query: str = "") -> dict:
        """用系统默认浏览器打开资源站（带 {query} 的地址会拼上关键词）。"""
        from urllib.parse import quote

        row = next((item for item in self._sites() if item["id"] == site_id), None)
        if row is None:
            return {"ok": False, "error": "not-found"}
        url = row["url"]
        text = str(query or "").strip()
        if "{query}" in url:
            url = url.replace("{query}", quote(text))
        return {**self.open_url(url), "url": url}

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

    def pick_download_dir(self) -> dict:
        """让用户挑一个下载目录。"""
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return self.set_download_option("download_dir", path)

    def open_download_dir(self) -> dict:
        target = self._downloads.download_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(str(target))  # noqa: S606
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "dir": str(target)}

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

    def pick_locale_proc(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Locale Emulator (LEProc.exe)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return self.set_locale_option("le_proc_path", path)

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

    def open_data_dir(self) -> dict:
        try:
            os.startfile(str(config.DATA_DIR))  # noqa: S606
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "dir": str(config.DATA_DIR)}

    def minimize_to_tray(self) -> bool:
        """关窗前调用：托盘可用且用户开了这个设置时，藏起来并返回 True。"""
        if self._window is None or self._tray is None:
            return False
        if not self._library.settings.get("close_to_tray"):
            return False
        try:
            self._window.hide()
        except Exception:
            return False
        self._tray.notify(config.APP_TITLE, "已缩小到托盘，游戏仍在后台运行。")
        return True

    # ------------------------------------------------------------------ #
    # 窗口拖拽 / 缩放
    # ------------------------------------------------------------------ #
    def drag_start(self) -> dict:
        if self._window is None:
            return {}
        x, y, w, h = winapi.get_rect(self._window)
        self._drag = {"x": x, "y": y, "w": w, "h": h,
                      "maximized": winapi.is_maximized(self._window)}
        return dict(self._drag)

    def drag_move(self, dx: float, dy: float) -> dict:
        if not self._drag or self._window is None:
            return {"ok": False}
        dx, dy = int(dx), int(dy)
        if self._drag.get("maximized"):
            # 最大化状态下拖动工具条：先还原窗口，再跟着鼠标走（与系统行为一致）
            winapi.restore(self._window)
            x, y, w, h = winapi.get_rect(self._window)
            self._drag = {"x": x - dx, "y": y - dy, "w": w, "h": h, "maximized": False}
        winapi.set_rect(self._window, self._drag["x"] + int(dx), self._drag["y"] + int(dy),
                        0, 0, move=True, size=False)
        return {"ok": True}

    def drag_end(self) -> dict:
        self._drag = None
        return {"ok": True}

    def resize_start(self) -> dict:
        if self._window is None:
            return {}
        x, y, w, h = winapi.get_rect(self._window)
        return {"x": x, "y": y, "w": w, "h": h}

    def resize_apply(self, x: int, y: int, width: int, height: int, edge: str = "") -> dict:
        if self._window is None:
            return {"ok": False}
        scale = winapi.dpi_scale(self._window)
        min_w = int(self._window.min_size[0] * scale)
        min_h = int(self._window.min_size[1] * scale)
        width, height = int(width), int(height)
        if width < min_w:
            if "w" in edge:
                x += width - min_w
            width = min_w
        if height < min_h:
            if "n" in edge:
                y += height - min_h
            height = min_h
        winapi.set_rect(self._window, x, y, width, height)
        return {"ok": True}

    # ------------------------------------------------------------------ #
    # 导入 / 删除
    # ------------------------------------------------------------------ #
    def pick_executable(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("可执行文件 (*.exe;*.bat;*.cmd)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        paths = [str(p) for p in result]
        added = [self._import_one(p) for p in paths]
        games = [g for g in added if g]
        skipped = [p for p, game in zip(paths, added) if not game]
        return {"ok": True, "games": games, "skipped": skipped}

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
        games = self._library.all()
        payload = {
            "app": config.APP_NAME,
            "version": config.VERSION,
            "exported_at": int(time.time()),
            "games": games,
            "settings": dict(self._library.settings),
        }
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

        added: list[dict] = []
        skipped = 0
        ids = {g["id"] for g in self._library.all()}
        for row in data["games"]:
            if not isinstance(row, dict):
                continue
            exe = str(row.get("exe") or "")
            if not exe or self._library.find_by_exe(exe):
                skipped += 1
                continue
            record = dict(row)
            if not record.get("id") or record["id"] in ids:
                record["id"] = uuid.uuid4().hex[:12]
            ids.add(record["id"])
            record.setdefault("images", [])
            record.setdefault("background", "")
            self._library.add(record)
            added.append(_public(record, self._pm))
        if added:
            self._emit("games:imported", {"games": added,
                                          "ids": [g["id"] for g in added], "ignored": skipped})
        config.log(f"library imported: +{len(added)} / skipped={skipped}")
        return {"ok": True, "added": len(added), "skipped": skipped, "games": added}

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

    def reveal(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False}
        process.reveal(game["exe"])
        return {"ok": True}

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

    def search(self, game_id: str, query: str | None = None) -> dict:
        """手动/自动搜索（同步返回候选列表）。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        if query:
            queries = [query.strip()]
        else:
            info = detect.describe_path(Path(game["exe"]))
            queries = (game.get("strong_queries") or info["strong_queries"]
                       or game.get("queries") or info["queries"])
        result = self._sources.resolve(queries, threshold=0.75)
        if result.get("ok"):
            self._apply_source(game_id, result["source"], result["source_id"],
                               name=result.get("name", ""), source="auto",
                               score=result.get("score"),
                               query=(result.get("query") or [""])[0])
            return {"ok": True, "game": _public(self._library.get(game_id), self._pm)}
        self._library.update(
            game_id,
            metadata_state="notfound",
            metadata_note=_resolve_note(result.get("reason")),
            candidates=result.get("candidates") or [],
            queries=queries,
        )
        return {
            "ok": False,
            "reason": result.get("reason"),
            "candidates": result.get("candidates") or [],
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

    def apply_window_icon(self, game_id: str) -> dict:
        """把窗口/任务栏图标换成该游戏的自定义图标；空字符串表示恢复默认。"""
        if self._window is None:
            return {"ok": False}
        path = ""
        if game_id:
            game = self._library.get(game_id)
            url = (game or {}).get("custom_icon") or ""
            if url:
                path = str(config.USER_ICON_DIR / url.split("/")[-1].split("?")[0])
        winapi.set_icon(self._window, path or None)
        return {"ok": True}

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

    def _on_game_exit(self, game_id: str, seconds: float) -> None:
        """会话结束：结算时长、记一条会话历史、清掉会话标记。"""
        game = self._library.get(game_id)
        if not game:
            return
        now = int(time.time())
        started = int(game.get("play_started_at") or 0) or int(now - seconds)
        history = list(game.get("sessions") or [])
        history.append({"started_at": started, "ended_at": now, "seconds": int(seconds)})
        self._library.update(
            game_id,
            play_started_at=0, play_pid=0, play_launcher_pid=0, play_heartbeat=0,
            sessions=history[-50:],
        )
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
                config.log(f"reattached running game {game['id']} pid={game.get('play_pid')}")
                self._start_heartbeat()
                self._watch(game["id"])
                continue
            beat = int(game.get("play_heartbeat") or 0) or started
            seconds = max(0, min(beat, now) - started)
            self._library.update(game["id"], play_started_at=0, play_pid=0,
                                 play_launcher_pid=0, play_heartbeat=0)
            if seconds >= self.HEARTBEAT_SECONDS:
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
