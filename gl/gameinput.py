"""给游戏窗口发输入（自检脚本与钩子查找器共用）。

踩过的坑：很多日文 VN（含 WillPlus/AdvHD）**空格键是隐藏/显示文本框**，不是推进 ——
用空格翻页看起来就像在「右键隐藏框」，词永远不动。所以这里默认**左键点文本框区域**，
其次回车；窗口不在前台、光标位置又不属于这个窗口时一律不发（免得点到别的程序上）。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               wintypes.DWORD, ctypes.c_void_p]
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint,
                               ctypes.c_void_p]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

VK_RETURN = 0x0D
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def ensure_dpi_awareness() -> str:
    """把本进程设成 DPI 感知（启动器本身是 SYSTEM_AWARE）。

    不设的话：GetWindowRect 给「虚拟化」坐标、而屏幕 BitBlt 用物理坐标，两者对不上
    —— 抓图/点击会落到隔壁窗口上（实测踩过这个坑）。
    """
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)      # SYSTEM_DPI_AWARE
        return "system"
    except Exception:
        try:
            ctypes.WinDLL("user32").SetProcessDPIAware()
            return "legacy"
        except Exception:
            return ""


ensure_dpi_awareness()


def foreground(hwnd: int) -> bool:
    try:
        return int(user32.GetForegroundWindow() or 0) == int(hwnd)
    except Exception:
        return False


def clickable(hwnd: int, point) -> bool:
    """光标位置上确实是这个窗口吗？（抢不到前台时也能安全地点击）"""
    try:
        target = user32.WindowFromPoint(point)
        if not target:
            return False
        return int(user32.GetAncestor(target, 2) or 0) == int(hwnd)   # GA_ROOT
    except Exception:
        return False


def advance(hwnd: int, *, key: int = VK_RETURN) -> str:
    """往游戏窗口送一次「下一句」；返回用了哪种方式，空串代表没送出去。"""
    if not hwnd:
        return ""
    rect = wintypes.RECT()
    if user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        point = wintypes.POINT(rect.right // 2, int(rect.bottom * 0.78))
        user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
        user32.SetCursorPos(point.x, point.y)
        time.sleep(0.1)
        if foreground(hwnd) or clickable(hwnd, point):
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
            time.sleep(0.05)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
            return f"左键点击 ({point.x},{point.y})"
    if foreground(hwnd):
        user32.keybd_event(key, 0, 0, None)
        time.sleep(0.05)
        user32.keybd_event(key, 0, 2, None)
        return "回车"
    return ""
