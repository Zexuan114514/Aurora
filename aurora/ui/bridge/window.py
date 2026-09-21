"""窗口 / 托盘 / 主题 / 图标桥接（P3 从 gl/api.py 原样搬出）。

方法体逐字未改；`config` 与 `winapi` 仍指向 gl 遗留模块，P3.2 收口到 aurora.platform。
"""
from __future__ import annotations

from aurora.platform import winapi
from gl import config   # TODO(P3.6): config 收口到 aurora.infra


class WindowBridgeMixin:
    """窗口命令、拖拽缩放、主题与图标、托盘最小化。"""


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


    def apply_window_theme(self, is_light: bool) -> dict:
        """让 Windows 外框（暗色模式 / 描边）跟随界面主题。"""
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        from gl import winapi

        dark = not bool(is_light)
        return {"ok": winapi.set_dark_frame(self._window, dark), "dark": dark}


    def apply_window_icon(self, game_id: str) -> dict:
        """把窗口/任务栏图标换成该游戏的自定义图标；空字符串表示恢复默认。"""
        if self._window is None:
            return {"ok": False}
        path = ""
        if game_id:
            game = self._library.get(game_id)
            url = (game or {}).get("custom_icon") or ""
            if url:
                path = str(config.ICON_SOURCE_DIR / url.split("/")[-1].split("?")[0])
        winapi.set_icon(self._window, path or None)
        return {"ok": True}


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


    def set_tray(self, tray) -> None:
        """由 main.py 注入托盘控制器（没有托盘时为 None）。"""
        self._tray = tray
