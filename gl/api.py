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

# 桥接层共享的投影与常量搬到了 aurora/ui/bridge/shared.py（P3.3）
from aurora.ui.bridge.shared import (  # noqa: F401  (re-export)
    IMAGE_EXTS, LAUNCHABLE_EXTS, NOTES, _public, _resolve_note,
)


from aurora.ui.bridge.library import LibraryBridgeMixin
from aurora.ui.bridge.metadata import MetadataBridgeMixin
from aurora.ui.bridge.settings import SettingsBridgeMixin
from aurora.ui.bridge.vntext import VnTextBridgeMixin
from aurora.ui.bridge.shell import ShellBridgeMixin
from aurora.ui.bridge.window import WindowBridgeMixin


class Api(WindowBridgeMixin, ShellBridgeMixin, SettingsBridgeMixin, LibraryBridgeMixin,
          MetadataBridgeMixin, VnTextBridgeMixin):
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

    def scan_downloads(self) -> dict:
        """手动扫一遍下载目录（忽略“已处理”记录）。"""
        res = self._downloads.scan_now()
        if res.get("handled"):
            self._emit("downloads:status", {
                "kind": "imported", "names": res["handled"][:6],
                "count": res.get("imported") or 0,
            })
        return {"ok": bool(res.get("ok")), **res}

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
