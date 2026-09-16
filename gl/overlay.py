"""译文悬浮窗：透明、无边框、置顶，默认鼠标穿透。

用 pywebview 的第二个窗口承载（和主窗口同一个 GUI 后端），
通过 evaluate_js 推译文，窗口位置/尺寸/样式记在设置里。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from pathlib import Path

import webview

from . import config

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]

HTML_PATH = Path(__file__).resolve().parent / "web" / "overlay.html"


class OverlayBridge:
    """悬浮窗页面能调到的接口（pywebview 的 js_api）。"""

    def __init__(self, owner: "Overlay") -> None:
        self._owner = owner

    def ready(self) -> dict:
        return self._owner.initial_payload()

    def save_bounds(self, x, y, width, height) -> dict:
        return self._owner.save_bounds(int(x), int(y), int(width), int(height))

    def action(self, name: str, payload=None) -> dict:
        return self._owner.handle_action(str(name or ""), payload)


class Overlay:
    def __init__(self, *, get_settings, set_option, on_action) -> None:
        self._get_settings = get_settings
        self._set_option = set_option
        self._on_action = on_action
        self._window: webview.Window | None = None
        self._lock = threading.RLock()
        self._click_through = True
        self._visible = False

    # ------------------------------------------------------------------ #
    def _view(self) -> dict:
        cfg = (self._get_settings() or {}).get("vntext_overlay") or {}
        return {
            "x": int(cfg.get("x") or 0),
            "y": int(cfg.get("y") or 0),
            "width": int(cfg.get("w") or 760),
            "height": int(cfg.get("h") or 150),
            "font": int(cfg.get("font") or 20),
            "opacity": float(cfg.get("opacity") or 0.9),
            "mode": str(cfg.get("mode") or "translated"),
            "click_through": bool(cfg.get("click_through", True)),
        }

    def initial_payload(self) -> dict:
        view = self._view()
        return {"ok": True, "style": view, "click_through": self._click_through,
                "lines": {"source": "", "translation": "", "status": "idle",
                          "notice": "", "provider": ""}}

    def ensure(self) -> bool:
        """确保悬浮窗存在（没有就创建）。"""
        with self._lock:
            if self._window is not None:
                return True
            if not HTML_PATH.is_file():
                config.log(f"overlay html missing: {HTML_PATH}")
                return False
            view = self._view()
            screen_w, screen_h = _screen_size()
            x = view["x"] or max(40, (screen_w - view["width"]) // 2)
            y = view["y"] or max(40, screen_h - view["height"] - 120)
            try:
                self._window = webview.create_window(
                    "Aurora 翻译", url=str(HTML_PATH),
                    js_api=OverlayBridge(self),
                    width=view["width"], height=view["height"], x=x, y=y,
                    frameless=True, on_top=True, transparent=True,
                    background_color="#000000", resizable=True, easy_drag=False)
            except Exception as exc:
                config.log(f"overlay create failed: {exc}")
                self._window = None
                return False
            self._click_through = view["click_through"]
            self._apply_click_through()
            self._visible = True
            return True

    def _hwnd(self) -> int:
        window = self._window
        if window is None:
            return 0
        try:
            handle = window.native.Handle
            return handle.ToInt64() if hasattr(handle, "ToInt64") else int(str(handle))
        except Exception:
            return 0

    def _apply_click_through(self) -> bool:
        hwnd = self._hwnd()
        if not hwnd:
            return False
        style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
        base = style | WS_EX_LAYERED | WS_EX_TOOLWINDOW
        if self._click_through:
            base |= WS_EX_TRANSPARENT
        else:
            base &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, base)
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return True

    def set_click_through(self, on: bool, *, persist: bool = True) -> dict:
        with self._lock:
            self._click_through = bool(on)
            ok = self._apply_click_through()
        if persist:
            self._save({"click_through": self._click_through})
        self.update({"click_through": self._click_through})
        return {"ok": ok, "click_through": self._click_through}

    def toggle_click_through(self) -> dict:
        return self.set_click_through(not self._click_through)

    def visible(self) -> bool:
        return bool(self._window is not None and self._visible)

    def show(self) -> dict:
        if not self.ensure():
            return {"ok": False, "error": "overlay-unavailable"}
        try:
            self._window.show()
        except Exception:
            pass
        self._visible = True
        self.update({})
        return {"ok": True}

    def hide(self) -> dict:
        window = self._window
        if window is None:
            return {"ok": True}
        try:
            window.hide()
        except Exception:
            pass
        self._visible = False
        return {"ok": True}

    def close(self) -> dict:
        window = self._window
        self._window = None
        self._visible = False
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass
        return {"ok": True}

    # ------------------------------------------------------------------ #
    def _save(self, patch: dict) -> None:
        cfg = dict((self._get_settings() or {}).get("vntext_overlay") or {})
        cfg.update(patch)
        try:
            self._set_option("vntext_overlay", cfg)
        except Exception as exc:
            config.log(f"overlay save failed: {exc}")

    def save_bounds(self, x: int, y: int, width: int, height: int) -> dict:
        self._save({"x": x, "y": y, "w": max(320, width), "h": max(80, height)})
        return {"ok": True}

    def set_style(self, patch: dict) -> dict:
        clean = {}
        if "font" in patch:
            clean["font"] = max(12, min(40, int(patch["font"])))
        if "opacity" in patch:
            clean["opacity"] = max(0.35, min(1.0, float(patch["opacity"])))
        if "mode" in patch:
            clean["mode"] = "bilingual" if str(patch["mode"]) == "bilingual" else "translated"
        if clean:
            self._save(clean)
        self.update({"style": self._view()})
        return {"ok": True, "style": self._view()}

    def handle_action(self, name: str, payload=None) -> dict:
        """悬浮窗上的按钮：交给上层的动作分发处理。"""
        if name == "toggle_mode":
            mode = "bilingual" if self._view()["mode"] == "translated" else "translated"
            return self.set_style({"mode": mode})
        if name == "font":
            return self.set_style({"font": payload if isinstance(payload, int)
                                   else int((payload or {}).get("font") or 20)})
        if name == "opacity":
            value = payload if isinstance(payload, (int, float)) else (payload or {}).get("opacity")
            return self.set_style({"opacity": float(value or 0.9)})
        if name == "click_through":
            return self.set_click_through(bool(payload if payload is not None else True))
        try:
            return self._on_action(name, payload) or {"ok": True}
        except Exception as exc:
            config.log(f"overlay action failed [{name}]: {exc}")
            return {"ok": False, "error": str(exc)}

    def update(self, payload: dict) -> None:
        window = self._window
        if window is None:
            return
        data = dict(payload or {})
        data.setdefault("style", self._view())
        data["click_through"] = self._click_through
        try:
            import json

            window.evaluate_js(f"window.vnUpdate && window.vnUpdate({json.dumps(data, ensure_ascii=False)})")
        except Exception as exc:
            config.log(f"overlay update failed: {exc}")


def _screen_size() -> tuple[int, int]:
    try:
        return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except Exception:
        return (1920, 1080)
