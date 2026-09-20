"""Win32 托盘图标原语：纯 ctypes 实现（P3.9-f 从 gl/tray.py 搬入）。"""
from __future__ import annotations

from aurora.infra.tasks import default_runner

import ctypes
import threading
from ctypes import wintypes
from pathlib import Path

from gl import config

WM_APP = 0x8000
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002

ID_SHOW = 1001
ID_QUIT = 1002

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                            wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HANDLE),
        ("hIcon", wintypes.HANDLE), ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HANDLE),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE), ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HANDLE),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# 句柄是 64 位的，argtypes 必须写清楚，否则 ctypes 会按 32 位 int 传参而报
# 「int too long to convert」
_LPRECT = ctypes.POINTER(wintypes.RECT)
_LPPOINT = ctypes.POINTER(wintypes.POINT)
_LPMSG = ctypes.POINTER(wintypes.MSG)

_user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
_user32.RegisterClassExW.restype = wintypes.WORD
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                 wintypes.LPARAM]
_user32.GetMessageW.argtypes = [_LPMSG, wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = [_LPMSG]
_user32.DispatchMessageW.argtypes = [_LPMSG]
_user32.DispatchMessageW.restype = ctypes.c_longlong
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                   wintypes.LPARAM]
_user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
_user32.LoadIconW.restype = wintypes.HANDLE
_user32.CreatePopupMenu.argtypes = []
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                                wintypes.LPCWSTR]
_user32.DestroyMenu.argtypes = [wintypes.HMENU]
_user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, _LPRECT]
_user32.TrackPopupMenu.restype = wintypes.UINT
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.GetCursorPos.argtypes = [_LPPOINT]
_user32.PostQuitMessage.argtypes = [ctypes.c_int]
_user32.DefWindowProcW.restype = ctypes.c_longlong

_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
_shell32.Shell_NotifyIconW.restype = wintypes.BOOL

_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HANDLE


class TrayIcon:
    """一个托盘图标：左键唤回窗口，右键出「显示 / 退出」菜单。"""

    def __init__(self, icon: str | Path | None, tooltip: str,
                 on_show, on_quit) -> None:
        self._icon = Path(icon) if icon else (config.PKG_DIR / "assets" / "aurora.ico")
        self._tooltip = (tooltip or config.APP_TITLE)[:120]
        self._on_show = on_show
        self._on_quit = on_quit
        self._hwnd: int | None = None
        self._nid: NOTIFYICONDATAW | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._alive = False
        self._wndproc_ref = None   # 必须持有引用，否则回调会被回收

    # ------------------------------------------------------------------ #
    @property
    def alive(self) -> bool:
        return self._alive and self._hwnd is not None

    def start(self, timeout: float = 6.0) -> bool:
        if self.alive:
            return True
        self._thread = default_runner().spawn("appshell.tray", self._run,
                                              thread_name="aurora-tray")
        self._ready.wait(timeout)
        if not self.alive:
            config.log("tray: failed to start")
            return False
        config.log("tray: started")
        return True

    def stop(self) -> None:
        if self._hwnd:
            try:
                _user32.PostMessageW(wintypes.HWND(self._hwnd), WM_CLOSE, 0, 0)
            except Exception:
                pass
        self._alive = False
        self._hwnd = None

    def notify(self, title: str, text: str) -> None:
        """气泡提示（失败就算了）。"""
        if not self.alive or not self._nid:
            return
        try:
            self._nid.uFlags = NIF_INFO
            self._nid.szInfo = (text or "")[:250]
            self._nid.szInfoTitle = (title or config.APP_TITLE)[:60]
            self._nid.dwInfoFlags = 0x00000001  # NIIF_INFO
            _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        try:
            self._create()
        except Exception as exc:
            config.log(f"tray: {exc}")
            self._ready.set()
            return
        try:
            msg = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            config.log(f"tray loop: {exc}")
        finally:
            self._remove()
            self._alive = False

    def _create(self) -> None:
        instance = _kernel32.GetModuleHandleW(None)
        class_name = f"AuroraTray_{id(self):x}"

        def handler(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_APP + 1:
                    if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                        self._call(self._on_show)
                    elif lparam == WM_RBUTTONUP:
                        self._menu(hwnd)
                elif msg == WM_COMMAND:
                    code = int(wparam) & 0xFFFF
                    if code == ID_SHOW:
                        self._call(self._on_show)
                    elif code == ID_QUIT:
                        self._call(self._on_quit)
                        return 0
                elif msg == WM_CLOSE:
                    _user32.DestroyWindow(hwnd)
                    return 0
                elif msg == WM_DESTROY:
                    _user32.PostQuitMessage(0)
                    return 0
            except Exception as exc:
                config.log(f"tray proc: {exc}")
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(handler)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = instance
        wc.lpszClassName = class_name
        if not _user32.RegisterClassExW(ctypes.byref(wc)):
            raise OSError(f"RegisterClassExW failed: {ctypes.get_last_error()}")

        self._hwnd = int(_user32.CreateWindowExW(
            0, class_name, config.APP_TITLE, 0, 0, 0, 0, 0, None, None, instance, None))
        if not self._hwnd:
            raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")

        icon = self._load_icon()
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = wintypes.HWND(self._hwnd)
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP + 1
        nid.hIcon = icon
        nid.szTip = self._tooltip
        if not _shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            raise OSError("Shell_NotifyIconW failed")
        self._nid = nid
        self._alive = True
        self._ready.set()

    def _load_icon(self):
        path = self._icon
        if path.suffix.lower() != ".ico":
            try:
                from .winapi import _as_ico

                path = _as_ico(path) or path
            except Exception:
                pass
        handle = _user32.LoadImageW(None, str(path), IMAGE_ICON, 0, 0,
                                    LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if handle:
            return handle
        # IDI_APPLICATION：用整数资源 id 调用需要手工构造指针
        return _user32.LoadIconW(None, ctypes.cast(ctypes.c_void_p(32512),
                                                   wintypes.LPCWSTR))

    def _menu(self, hwnd) -> None:
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        try:
            _user32.AppendMenuW(menu, MF_STRING, ID_SHOW, "显示 Aurora")
            _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            _user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出")
            point = wintypes.POINT()
            _user32.GetCursorPos(ctypes.byref(point))
            _user32.SetForegroundWindow(hwnd)
            command = _user32.TrackPopupMenu(
                menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                point.x, point.y, 0, hwnd, None)
            if command == ID_SHOW:
                self._call(self._on_show)
            elif command == ID_QUIT:
                self._call(self._on_quit)
            _user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            _user32.DestroyMenu(menu)

    def _remove(self) -> None:
        if self._nid is not None:
            try:
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
            self._nid = None

    @staticmethod
    def _call(callback) -> None:
        try:
            if callback:
                callback()
        except Exception as exc:
            config.log(f"tray callback: {exc}")
