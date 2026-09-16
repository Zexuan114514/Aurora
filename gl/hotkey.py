"""全局热键（RegisterHotKey + 消息循环）。

穿透状态下悬浮窗点不到，所以必须用系统级热键切回来。
注册失败（被别的软件占用）不影响其它功能，只记日志。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from . import config

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

user32 = ctypes.WinDLL("user32", use_last_error=True)


class Hotkeys:
    """注册一组全局热键，按下的回调在独立线程里执行。"""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._binds: list[tuple[int, int, int]] = []      # (id, modifiers, vk)
        self._handlers: dict[int, callable] = {}
        self._registered: list[int] = []

    def bind(self, hotkey_id: int, modifiers: int, vk: int, handler) -> None:
        self._binds.append((hotkey_id, modifiers | MOD_NOREPEAT, vk))
        self._handlers[hotkey_id] = handler

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="aurora-hotkeys")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            user32.PostThreadMessageW(self._thread.native_id, 0x0012, 0, 0)   # WM_QUIT
        except Exception:
            pass

    def _loop(self) -> None:
        for hotkey_id, modifiers, vk in self._binds:
            if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                self._registered.append(hotkey_id)
            else:
                config.log(f"RegisterHotKey failed id={hotkey_id} vk={vk} "
                           f"err={ctypes.get_last_error()}")
        if not self._registered:
            return
        msg = wintypes.MSG()
        while not self._stop.is_set():
            got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                handler = self._handlers.get(int(msg.wParam))
                if handler:
                    try:
                        handler()
                    except Exception as exc:
                        config.log(f"hotkey handler failed: {exc}")
        for hotkey_id in self._registered:
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass
        self._registered.clear()
