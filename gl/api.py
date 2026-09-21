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

from aurora.app.events import EventBus, default_bus
from aurora.infra.dialogs import WebviewFileDialog
from aurora.app.services.library import LibraryService
from aurora.app.services.hooksearch import HookSearchService
from aurora.app.services.launch import LaunchService
from aurora.app.services.metadata import MetadataService
from aurora.app.services.translation import TranslationService
from aurora.app.services.vntext import VnTextService
from aurora.app.services.settings import SettingsService
from aurora.app.services.plugins import PluginsService
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
        self._settings = SettingsService(self._library, self._sources)
        #: P6.2：插件目录（data/plugins/**）的加载与状态查询
        self._plugins_service = PluginsService(config.DATA_DIR, logger=config.log)
        self._library_service = LibraryService(self._library, self._pm,
                                             auto_search_async=lambda gid: self._metadata._auto_search_async(gid),
                                             apply_window_icon=self.apply_window_icon)
        self._window: webview.Window | None = None
        #: P3.9-h：文件对话框走端口（窗口晚于 Api 创建，用 getter 惰性取）
        self._dialogs = WebviewFileDialog(lambda: self._window)
        self._drag: dict | None = None
        self._lock = threading.RLock()
        #: P3.7：后台任务统一走 TaskRunner（心跳先收编，其余逐个搬）
        self._tasks = TaskRunner(max_workers=8, name_prefix="aurora-task")
        #: P3.7：事件先进 EventBus（信封见 contracts/events.md），再由唯一出口推给前端
        self._events = default_bus()      # P3.8：与核心模块/服务共用进程级总线
        self._events.subscribe("*", self._dispatch_event)
        self._translator = linetrans.LineTranslator(
            settings_getter=lambda: self._library.settings,
            on_event=None)                # P3.7：译文事件改走总线
        self._vn_engine = vntext.VnTextEngine(
            settings_getter=lambda: self._library.settings,
            on_line=None, on_status=None)   # P3.7：文本/状态改走总线
        self._translation = TranslationService(self._library, self._pm, self._translator, self._tasks)
        self._metadata = MetadataService(self._library, self._pm, self._sources, self._tasks,
                                         translation=self._translation, import_one=self._import_one)
        # P3.7：核心模块（翻译 / 文本源 / 会话 / 下载）没有回调时向默认总线发内部事件，这里订阅接上
        bus = default_bus()
        bus.subscribe("engine.translate",
                      lambda env: self._on_translate_event(
                          str(env["payload"].get("kind") or ""), env["payload"]))
        bus.subscribe("engine.vntext_line", lambda env: self._on_vntext_line(env["payload"]))
        bus.subscribe("engine.vntext_status", lambda env: self._emit("vntext:status", env["payload"]))
        bus.subscribe("engine.session_found", lambda env: self._on_game_found(
            env["payload"].get("game_id"), env["payload"].get("pid")))
        bus.subscribe("engine.session_exit", lambda env: self._on_game_exit(
            env["payload"].get("game_id"), env["payload"].get("seconds") or 0.0))
        bus.subscribe("engine.downloads_status", lambda env: self._emit("downloads:status", env["payload"]))
        self._tray = None          # 由 main.py 注入托盘控制器（可选）
        # 获取游戏：盯着下载目录，出现新游戏就自动导入
        self._downloads = downloads.DownloadWatcher(
            settings_getter=lambda: self._library.settings,
            save_setting=self._library.set_setting,
            import_fn=lambda paths: len(self.import_dropped(paths).get("games") or []),
            status_fn=None,          # P3.7：状态改走事件总线
        )
        self._downloads.start()
        self._launch = LaunchService(self._library, self._pm, self._tasks, engine=self._vn_engine,
                                     start_vntext=self.start_vntext, stop_vntext=self.stop_vntext,
                                     downloads_getter=lambda: self._downloads)
        # 网络：让 gl.sources.net 知道当前用哪条代理路线
        netproxy.set_settings_provider(lambda: self._library.settings)
        self._pm.set_callbacks()      # P3.7：会话事件改走总线
        # 游戏内翻译：文本源 / 逐句翻译 / 悬浮窗 / 全局热键
        self._overlay = overlay.Overlay(
            get_settings=lambda: self._library.settings,
            set_option=self._library.set_setting,
            on_action=self._on_overlay_action)
        self._hotkeys = hotkey.Hotkeys()
        self._hotkeys.bind(1, hotkey.MOD_CONTROL | hotkey.MOD_ALT, 0x54,   # Ctrl+Alt+T
                           self._toggle_overlay_click_through)
        self._hotkeys.bind(2, hotkey.MOD_CONTROL | hotkey.MOD_ALT, 0x59,   # Ctrl+Alt+Y
                           self._toggle_overlay_visible)
        # 主热键被别的软件占用时的备选（Ctrl+Shift+F9 / Ctrl+Shift+F10）
        self._hotkeys.bind(3, hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0x78,
                           self._toggle_overlay_click_through)
        self._hotkeys.bind(4, hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0x79,
                           self._toggle_overlay_visible)
        self._hooksearch_service = HookSearchService(self._library, self._pm, self._vn_engine,
                                                    self._tasks, overlay=self._overlay)
        self._vntext = VnTextService(self._library, self._pm, self._vn_engine, self._translator,
                                     self._overlay, self._hotkeys, self._tasks,
                                     stop_hook_search=self.stop_hook_search)
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
