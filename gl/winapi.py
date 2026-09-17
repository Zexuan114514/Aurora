"""Windows 原生窗口效果：圆角、暗色边框、最大化/还原。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from . import config

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

SW_MAXIMIZE = 3
SW_RESTORE = 9
SW_SHOW = 5

ASFW_ANY = -1

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

_dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

# 句柄是指针：不声明 argtypes/restype 在 64 位 Python 上会被截成 32 位
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetFocus.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.argtypes = [wintypes.HWND]


def _set_dwm(hwnd: int, attribute: int, value: int) -> bool:
    buf = ctypes.c_int(value)
    try:
        result = _dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), attribute, ctypes.byref(buf), ctypes.sizeof(buf)
        )
        return result == 0
    except Exception:
        return False


def handle_of(window) -> int | None:
    """获取 pywebview 窗口对应的 HWND。"""
    try:
        native = getattr(window, "native", None)
        if native is not None:
            handle = getattr(native, "Handle", None)
            if handle is not None:
                return int(handle)
    except Exception:
        pass
    try:
        hwnd = _user32.FindWindowW(None, str(window.title))
        return int(hwnd) if hwnd else None
    except Exception:
        return None


def find_window(title: str) -> int | None:
    """按标题找窗口（用于「第二次启动」时把已有窗口拉到前台）。"""
    try:
        hwnd = _user32.FindWindowW(None, str(title))
        return int(hwnd) if hwnd else None
    except Exception:
        return None


def focus_window(hwnd: int | None) -> bool:
    """还原（若最小化）并尽量置于前台。"""
    if not hwnd:
        return False
    try:
        handle = wintypes.HWND(int(hwnd))
        if _user32.IsIconic(handle):
            _user32.ShowWindow(handle, SW_RESTORE)
        _user32.ShowWindow(handle, SW_SHOW)
        try:
            _user32.AllowSetForegroundWindow(ASFW_ANY)
        except Exception:
            pass
        _user32.SetForegroundWindow(handle)
        _user32.BringWindowToTop(handle)
        if int(_user32.GetForegroundWindow() or 0) == int(handle):
            return True
        # Windows 默认不允许后台进程抢前台（实测从 Codex 终端里跑
        # 自检脚本时 SetForegroundWindow 直接返回失败）。把当前前台线程
        # 和游戏窗口线程临时「合流」再抢，就不受限了。
        _attach_thread_input(handle)
        if int(_user32.GetForegroundWindow() or 0) == int(handle):
            return True
        # 还是抢不到前台（用户正在别的窗口打字时 Windows 会锁前台）：至少把窗口
        # 抬到最上面 —— 用户看得见、鼠标点得到，OCR 抓屏幕也有内容。
        return raise_window(handle)
    except Exception:
        return False


def raise_window(hwnd) -> bool:
    """把窗口抬到 z 序最上面（不需要前台权限）。"""
    if not hwnd:
        return False
    try:
        HWND_TOP = 0
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_uint]
        _user32.SetWindowPos(wintypes.HWND(int(hwnd)), wintypes.HWND(HWND_TOP), 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        return True
    except Exception:
        return False


def _attach_thread_input(handle) -> None:
    """AttachThreadInput 版的强制前台（失败也无所谓，不影响其它功能）。"""
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        target_thread = _user32.GetWindowThreadProcessId(handle, None)
        current = wintypes.HWND(_user32.GetForegroundWindow() or 0)
        foreground_thread = _user32.GetWindowThreadProcessId(current, None) if current else 0
        my_thread = kernel32.GetCurrentThreadId()
        # 前台锁：Windows 在用户刚操作过别的窗口时会拒绝 SetForegroundWindow。
        # 敲一下 ALT 是业界通行的「解锁」手法（合成键，不影响用户输入）。
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        _user32.keybd_event(VK_MENU, 0, 0, None)
        _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
        attached = []
        for thread in {target_thread, foreground_thread}:
            if thread and thread != my_thread:
                attached.append((thread, bool(_user32.AttachThreadInput(thread, my_thread, True))))
        _user32.SetForegroundWindow(handle)
        _user32.SetFocus(handle)
        _user32.BringWindowToTop(handle)
        for thread, ok in attached:
            if ok:
                _user32.AttachThreadInput(thread, my_thread, False)
    except Exception:
        pass


#: 深色 / 浅色主题下的窗口外框描边
BORDER_DARK = 0x2E2E33
BORDER_LIGHT = 0xD6D6DC


def system_prefers_light() -> bool:
    """Windows 应用主题是否设为浅色（供 theme_mode = auto 用）。"""
    try:
        import winreg

        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value = int(winreg.QueryValueEx(key, "AppsUseLightTheme")[0] or 0)
        return value == 1
    except Exception:
        return False


def set_dark_frame(window, is_dark: bool) -> bool:
    """让窗口外框（暗色模式 / 描边）跟随界面主题。"""
    hwnd = handle_of(window)
    if not hwnd:
        return False
    ok = _set_dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if is_dark else 0)
    _set_dwm(hwnd, DWMWA_BORDER_COLOR, BORDER_DARK if is_dark else BORDER_LIGHT)
    return bool(ok)


def polish(window, corner: int = DWMWCP_ROUND, dark: bool = True) -> bool:
    """给无边框窗口加上圆角、暗色边框与阴影。"""
    hwnd = handle_of(window)
    if not hwnd:
        config.log("polish: hwnd not found")
        return False

    ok = _set_dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
    _set_dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, corner)
    # 极淡的边框，让圆角在浅色壁纸上也有轮廓
    _set_dwm(hwnd, DWMWA_BORDER_COLOR, BORDER_DARK if dark else BORDER_LIGHT)
    set_icon(hwnd)

    try:
        _user32.SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    except Exception:
        pass
    config.log(f"polish hwnd={hwnd} dark={ok} corner={corner}")
    return True


def _as_ico(path: Path) -> Path | None:
    """.ico 直接用；其它格式用 Pillow 转成临时 .ico（没有 Pillow 就放弃）。"""
    if path.suffix.lower() == ".ico":
        return path
    try:
        from PIL import Image

        cache = config.DATA_DIR / "icons" / "_converted"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / (path.stem + ".ico")
        if not target.exists() or target.stat().st_mtime < path.stat().st_mtime:
            img = Image.open(path).convert("RGBA")
            side = max(img.size)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
            canvas.resize((256, 256), Image.LANCZOS).save(
                target, format="ICO", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])
        return target
    except Exception as exc:
        config.log(f"icon convert failed: {exc}")
        return None


def set_icon(window_or_hwnd, path: str | Path | None = None) -> None:
    """设置窗口/任务栏图标；path 为空时用自带图标。"""
    hwnd = (handle_of(window_or_hwnd)
            if not isinstance(window_or_hwnd, int) else window_or_hwnd)
    if not hwnd:
        return
    ico = Path(path) if path else (config.PKG_DIR / "assets" / "aurora.ico")
    if not ico.exists():
        return
    ico = _as_ico(ico) or (config.PKG_DIR / "assets" / "aurora.ico")
    if not ico or not ico.exists():
        return
    try:
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1
        load = _user32.LoadImageW
        load.restype = wintypes.HANDLE
        big = load(None, str(ico), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        small = load(None, str(ico), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if big:
            _user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_BIG, big)
        if small:
            _user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_SMALL, small)
    except Exception as exc:
        config.log(f"set_icon failed: {exc}")


def maximize(window) -> None:
    hwnd = handle_of(window)
    if hwnd:
        _user32.ShowWindow(wintypes.HWND(hwnd), SW_MAXIMIZE)


def restore(window) -> None:
    hwnd = handle_of(window)
    if hwnd:
        _user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)


def is_maximized(window) -> bool:
    hwnd = handle_of(window)
    return bool(hwnd) and bool(_user32.IsZoomed(wintypes.HWND(hwnd)))


def toggle_maximize(window) -> bool:
    if is_maximized(window):
        restore(window)
        return False
    maximize(window)
    return True


# --------------------------------------------------------------------------- #
# 直接用 SetWindowPos 操作窗口，避免 pywebview 内部 DPI 换算不一致
# --------------------------------------------------------------------------- #
def get_rect(window) -> tuple[int, int, int, int]:
    """返回窗口的物理像素 (x, y, w, h)。"""
    hwnd = handle_of(window)
    if not hwnd:
        return (0, 0, 0, 0)
    rc = wintypes.RECT()
    _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    return (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)


def set_rect(window, x: int, y: int, width: int, height: int,
             move: bool = True, size: bool = True) -> None:
    hwnd = handle_of(window)
    if not hwnd:
        return
    flags = SWP_NOZORDER | SWP_NOACTIVATE
    if not move:
        flags |= SWP_NOMOVE
    if not size:
        flags |= SWP_NOSIZE
    _user32.SetWindowPos(
        wintypes.HWND(hwnd), None,
        int(x) if move else 0, int(y) if move else 0,
        int(width) if size else 0, int(height) if size else 0,
        flags,
    )


def dpi_scale(window) -> float:
    """窗口所在显示器的缩放比例（96dpi = 1.0）。"""
    hwnd = handle_of(window)
    try:
        if hwnd:
            return max(1.0, _user32.GetDpiForWindow(wintypes.HWND(hwnd)) / 96.0)
        return max(1.0, _user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0
