"""译文悬浮窗：透明、无边框、置顶，默认鼠标穿透。

用 pywebview 的第二个窗口承载（和主窗口同一个 GUI 后端），
通过 evaluate_js 推译文，窗口位置/尺寸/样式记在设置里。
"""
from __future__ import annotations

from aurora.infra.tasks import default_runner

import ctypes
import threading
import time
from ctypes import wintypes
from pathlib import Path

import webview

from . import config

GWL_EXSTYLE = -20
GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
WM_NCLBUTTONDOWN = 0x00A1
HTBOTTOMRIGHT = 17

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.ReleaseCapture.argtypes = []
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t,
                                ctypes.c_ssize_t]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

HTML_PATH = Path(__file__).resolve().parent / "web" / "overlay.html"


class OverlayBridge:
    """悬浮窗页面能调到的接口（pywebview 的 js_api）。"""

    def __init__(self, owner: "Overlay") -> None:
        self._owner = owner

    def ready(self) -> dict:
        return self._owner.initial_payload()

    def save_bounds(self, x, y, width, height) -> dict:
        return self._owner.save_bounds(int(x), int(y), int(width), int(height))

    def begin_resize(self) -> dict:
        return self._owner.begin_resize()

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
        self._resize_ready = False

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
            # 几何一律用默认值：实测保存/恢复会被 DPI 放大成整屏（3078x1887 落在
            # 1755x1097 的屏幕上），而且用户希望的正是「每次启动都回到合适大小」
            width, height = 760, 150
            # 位置交给 pywebview 自己居中：屏幕指标与 create_window 的坐标空间在
            # 高 DPI 下不是同一套（实测 175% 缩放时会算出屏幕外的坐标），
            # 所以不再用「算出来的默认坐标」，避免把窗口丢到屏幕外。
            # 位置一律交给 pywebview 居中：实测保存下来的坐标是「逻辑×dpr」的混合空间，
            # 再喂回去会被乘第二次（本次现场：保存 y=1243、屏幕只高 1097 → 窗口在屏幕外）
            place: dict = {}
            # 兜底：老配置可能存了屏幕外的坐标（DPI 混用过），钳回可见区域，
            # 否则窗口只有任务栏预览能看到，用户既看不到也拖不到
            place.clear()
            view["width"], view["height"] = width, height
            try:
                self._window = webview.create_window(
                    "Aurora 翻译", url=str(HTML_PATH),
                    js_api=OverlayBridge(self),
                    width=width, height=height, **place,
                    frameless=True, on_top=True, hidden=False,
                    # 不再用 transparent=True：那是逐像素 alpha 的分层窗口，
                    # 命中测试按像素 alpha 走，外部清 WS_EX_TRANSPARENT 也点不到
                    # （反馈里的「提示已可点击但鼠标仍穿透」就是它）。改成实心窗，
                    # 靠 WS_EX_TRANSPARENT 开关穿透，行为可预期。
                    background_color="#14161f", resizable=True, easy_drag=False)
            except Exception as exc:
                config.log(f"overlay create failed: {exc}")
                self._window = None
                return False
            self._click_through = view["click_through"]
            self._enable_resize_border()
            default_runner().spawn("overlay.resize", self._resize_border_later,
                                   thread_name="aurora-overlay-resize")
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
        # 不再用 WS_EX_TOOLWINDOW：那样窗口不进任务栏/Alt+Tab，用户既找不到也没法把它
        # 切到前台（反馈里「进程在但看不到窗口」就是这个坑）
        base = (style | WS_EX_LAYERED) & ~WS_EX_TOOLWINDOW
        if self._click_through:
            base |= WS_EX_TRANSPARENT
        else:
            base &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, base)
        self._force_top()
        return True

    def _enable_resize_border(self) -> bool:
        """补上 WS_THICKFRAME：无边框窗口默认没有可拖的边框，鼠标移到边缘不会
        变成缩放光标（用户反馈「不知道怎么缩放」）。补上以后既能从任意边缘拖，
        右下角的手柄也能直接走 Windows 原生缩放。"""
        if self._resize_ready:
            return True
        hwnd = self._hwnd()
        if not hwnd:
            return False
        try:
            handle = wintypes.HWND(hwnd)
            style = user32.GetWindowLongW(handle, GWL_STYLE)
            user32.SetWindowLongW(handle, GWL_STYLE, style | WS_THICKFRAME)
            user32.SetWindowPos(handle, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                                | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
            # 读回来确认：pywebview 建窗时会用它自己的样式覆盖一次
            self._resize_ready = bool(
                user32.GetWindowLongW(handle, GWL_STYLE) & WS_THICKFRAME)
            return self._resize_ready
        except Exception as exc:
            config.log(f"overlay resize border failed: {exc}")
            return False

    def _resize_border_later(self) -> None:
        """窗口显示之后样式还可能被 pywebview 覆盖，退几步再补一次。"""
        for _ in range(8):
            if self._resize_ready or self._window is None:
                self._clamp_to_screen()
                return
            time.sleep(0.4)
            self._enable_resize_border()

    def _clamp_to_screen(self) -> bool:
        """窗口按 DPI 放大后可能有一部分在屏幕外，右下角的缩放手柄就够不到了；
        把它挪回可见区域。"""
        hwnd = self._hwnd()
        if not hwnd:
            return False
        try:
            handle = wintypes.HWND(hwnd)
            rect = wintypes.RECT()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            screen_w, screen_h = _screen_size()
            width, height = rect.right - rect.left, rect.bottom - rect.top
            x = min(max(0, rect.left), max(0, screen_w - width))
            y = min(max(0, rect.top), max(0, screen_h - height))
            if (x, y) == (rect.left, rect.top):
                return False
            config.log(f"overlay clamped {rect.left},{rect.top} -> {x},{y}")
            user32.SetWindowPos(handle, wintypes.HWND(HWND_TOPMOST), x, y, 0, 0,
                                SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            return True
        except Exception as exc:
            config.log(f"overlay clamp failed: {exc}")
            return False

    def _force_top(self) -> bool:
        """显式显示并抬到最前：光靠 pywebview 的 on_top 在游戏窗口前不够稳。"""
        hwnd = self._hwnd()
        if not hwnd:
            return False
        try:
            user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
        except Exception:
            pass
        return bool(user32.SetWindowPos(
            wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW))

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
        try:
            self._window.on_top = True      # pywebview 也支持运行时改置顶
        except Exception:
            pass
        self._force_top()
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

    def begin_resize(self) -> dict:
        """无边框窗口没有可拖的边框，把右下角交回 Windows 的原生缩放循环。

        用 PostMessage 而不是 SendMessage：原生缩放循环是模态的，SendMessage
        会把处理 JS 请求的线程一直卡到松开鼠标为止。
        """
        hwnd = self._hwnd()
        if not hwnd:
            return {"ok": False, "error": "no-window"}
        try:
            user32.ReleaseCapture()
            user32.PostMessageW(wintypes.HWND(hwnd), WM_NCLBUTTONDOWN,
                                ctypes.c_size_t(HTBOTTOMRIGHT), ctypes.c_ssize_t(0))
            return {"ok": True}
        except Exception as exc:
            config.log(f"overlay resize failed: {exc}")
            return {"ok": False, "error": str(exc)}

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
