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

from aurora.app.events import EventBus
from aurora.domain import session_rules
from aurora.infra.tasks import TaskRunner

# 桥接层共享的投影与常量搬到了 aurora/ui/bridge/shared.py（P3.3）
from aurora.ui.bridge.shared import (  # noqa: F401  (re-export)
    IMAGE_EXTS, LAUNCHABLE_EXTS, NOTES, _public, _resolve_note,
)


from aurora.ui.bridge.library import LibraryBridgeMixin
from aurora.ui.bridge.metadata import MetadataBridgeMixin
from aurora.ui.bridge.session import SessionBridgeMixin
from aurora.ui.bridge.settings import SettingsBridgeMixin
from aurora.ui.bridge.vntext import VnTextBridgeMixin
from aurora.ui.bridge.shell import ShellBridgeMixin
from aurora.ui.bridge.window import WindowBridgeMixin


class Api(WindowBridgeMixin, ShellBridgeMixin, SettingsBridgeMixin, LibraryBridgeMixin,
          MetadataBridgeMixin, VnTextBridgeMixin, SessionBridgeMixin):
    def __init__(self) -> None:
        self._library = Library()
        self._pm = process.ProcessManager()
        self._sources = SourceManager(self._library)
        self._window: webview.Window | None = None
        self._drag: dict | None = None
        self._busy: set[str] = set()
        self._lock = threading.RLock()
        #: P3.7：后台任务统一走 TaskRunner（心跳先收编，其余逐个搬）
        self._tasks = TaskRunner(max_workers=8, name_prefix="aurora-task")
        self._heartbeat = None
        #: P3.7：事件先进 EventBus（信封见 contracts/events.md），再由唯一出口推给前端
        self._events = EventBus()
        self._events.subscribe("*", self._dispatch_event)
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

    def shutdown(self) -> None:
        """应用退出前的收尾：停文本会话与下载监听 → 落盘 → 关停存储写线程。"""
        for name, action in (("vntext", self.stop_vntext),
                             ("downloads", self._downloads.stop)):
            try:
                action()
            except Exception as exc:
                config.log(f"{name} shutdown failed: {exc}")
        try:
            self._tasks.shutdown()          # 取消心跳等后台任务，避免非守护线程卡住退出
        except Exception as exc:
            config.log(f"tasks shutdown failed: {exc}")
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

    #: 运行中每隔多少秒把「还活着」写一次盘（用于崩溃/被强关时估算时长）
    HEARTBEAT_SECONDS = 30

    # ------------------------------------------------------------------ #
    def _emit(self, event: str, payload: dict) -> None:
        """发布事件：先进 EventBus（可订阅、可诊断），再由 `_dispatch_event` 推给前端。"""
        self._events.publish(event, payload)

    def _dispatch_event(self, envelope: dict) -> None:
        """EventBus 订阅者：把信封载荷推给页面（行为与旧 `_emit` 逐字一致）。"""
        if self._window is None:
            return
        import json

        event = envelope.get("topic") or ""
        payload = envelope.get("payload") or {}
        try:
            self._window.evaluate_js(
                f"window.__aurora && window.__aurora.emit({json.dumps(event)},"
                f"{json.dumps(payload, ensure_ascii=False)})"
            )
        except Exception as exc:
            config.log(f"emit failed {event}: {exc}")
