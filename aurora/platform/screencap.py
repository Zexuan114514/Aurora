"""屏幕/窗口截图原语：PrintWindow 优先、黑屏回退 BitBlt（P3.9 从 gl/screencap.py 搬入）。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
                               wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.EnumChildWindows.argtypes = [
    wintypes.HWND, ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
    wintypes.LPARAM]

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]

PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def windows_of(pid: int) -> list[dict]:
    """该进程的所有可见顶层窗口，按面积从大到小。"""
    pid = int(pid or 0)
    if not pid:
        return []
    found: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width > 200 and height > 150:
            found.append({"hwnd": int(hwnd), "rect": (rect.left, rect.top, width, height)})
        return True

    user32.EnumWindows(callback, 0)
    found.sort(key=lambda row: -(row["rect"][2] * row["rect"][3]))
    return found


def main_window(pid: int) -> dict | None:
    rows = windows_of(pid)
    return rows[0] if rows else None


def window_title(hwnd: int) -> str:
    """窗口标题（有些引擎会把标题当文本吐进钩子流，用来过滤噪声）。"""
    if not hwnd:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(wintypes.HWND(int(hwnd)), buffer, 512)
        return buffer.value.strip()
    except Exception:
        return ""


def window_titles(pid: int) -> list[str]:
    """该进程所有可见顶层窗口的标题（含视频子窗口那种）。

    有些引擎会把窗口标题当文本吐进钩子流（实测白色相簿2 的 `ActiveMovie Window`），
    这些标题要拿来当噪声过滤掉。
    """
    pid = int(pid or 0)
    if not pid:
        return []
    found: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        title = window_title(int(hwnd))
        if title and title not in found:
            found.append(title)
        return True

    try:
        user32.EnumWindows(callback, 0)
        # ActiveMovie 这类视频窗口是子窗口，顶层枚举看不到
        for hwnd, _rect in ((row["hwnd"], row["rect"]) for row in windows_of(pid)):
            user32.EnumChildWindows(wintypes.HWND(int(hwnd)), callback, 0)
    except Exception:
        pass
    return found


def is_exposed(hwnd: int) -> bool:
    """窗口是否真的显示在屏幕上（没被别的窗口盖住）。

    实测：D3D 引擎（如少女之剑的 AdvHD）用 PrintWindow 抓到的画面**没有对话框图层**
    —— 只有背景 CG；而对话框就在窗口里，用户看得见。所以 OCR 要用「屏幕上真实的
    像素」，必须先确认窗口是露出来的。
    """
    if not hwnd:
        return False
    try:
        handle = wintypes.HWND(int(hwnd))
        if not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
            return False
        rect = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return False
        GA_ROOT = 2
        for fx, fy in ((0.5, 0.5), (0.5, 0.8), (0.3, 0.5)):
            point = wintypes.POINT(int(rect.left + (rect.right - rect.left) * fx),
                                   int(rect.top + (rect.bottom - rect.top) * fy))
            top = user32.WindowFromPoint(point)
            # 注意：HWND 是 c_void_p，直接和 int 比会恒为 False（实测踩过），统一转 int
            if top and int(user32.GetAncestor(top, GA_ROOT) or 0) == int(hwnd):
                return True
        return False
    except Exception:
        return False


def _grab_bitmap(hwnd: int, width: int, height: int, use_print: bool):
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height        # 负数 = 自上而下，省一次翻转
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(info), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
    if not bitmap or not bits:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        return None
    old = gdi32.SelectObject(mem_dc, bitmap)
    ok = False
    if use_print:
        hwnd_dc = user32.GetDC(hwnd)
        if hwnd_dc:
            ok = bool(user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT))
            user32.ReleaseDC(hwnd, hwnd_dc)
    else:
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        ok = bool(gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc,
                               rect.left, rect.top, SRCCOPY))
    data = b""
    if ok and bits:
        data = ctypes.string_at(bits, width * height * 4)
    gdi32.SelectObject(mem_dc, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(None, screen_dc)
    return data if ok else None


def _bgr_from_bgra(data: bytes) -> bytes:
    out = bytearray(len(data) // 4 * 3)
    index = 0
    for i in range(0, len(data) - 3, 4):
        out[index] = data[i]
        out[index + 1] = data[i + 1]
        out[index + 2] = data[i + 2]
        index += 3
    return bytes(out)


def _looks_blank(bgr: bytes) -> bool:
    """整块几乎全黑 = PrintWindow 没画出来（DirectX 常见），需要换路。"""
    if not bgr:
        return True
    step = max(1, len(bgr) // 4096 // 3) * 3
    dark = total = 0
    for i in range(0, len(bgr) - 2, step):
        total += 1
        if bgr[i] < 8 and bgr[i + 1] < 8 and bgr[i + 2] < 8:
            dark += 1
    return total > 0 and dark / total > 0.985


def capture(window: dict, region: dict | None = None) -> dict:
    """抓一个窗口（或窗口内的相对区域）。

    region 用相对窗口的百分比 {x, y, w, h}（0~1），窗口移动/缩放后依然有效。
    窗口露在屏幕上时优先抓屏幕像素：D3D 引擎（实测 AdvHD）用 PrintWindow 抓到的是
    没有对话框图层的旧画面，OCR 会认出一片空白背景。
    """
    hwnd = int(window.get("hwnd") or 0)
    rect = wintypes.RECT()
    if not hwnd or not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return {"ok": False, "error": "no-window"}
    full_w = rect.right - rect.left
    full_h = rect.bottom - rect.top
    if full_w <= 0 or full_h <= 0:
        return {"ok": False, "error": "bad-window"}

    order = (False, True) if is_exposed(hwnd) else (True, False)
    for use_print in order:
        data = _grab_bitmap(hwnd, full_w, full_h, use_print)
        if not data:
            continue
        bgr = _bgr_from_bgra(data)
        if use_print and _looks_blank(bgr):
            continue                        # 黑屏，换 BitBlt 再试一次
        if not region:
            return {"ok": True, "error": "", "bgr": bgr, "width": full_w, "height": full_h,
                    "source": "print" if use_print else "screen"}
        x = max(0.0, min(1.0, float(region.get("x", 0))))
        y = max(0.0, min(1.0, float(region.get("y", 0))))
        w = max(0.01, min(1.0 - x, float(region.get("w", 1))))
        h = max(0.01, min(1.0 - y, float(region.get("h", 1))))
        cut_x, cut_y = int(full_w * x), int(full_h * y)
        cut_w, cut_h = max(1, int(full_w * w)), max(1, int(full_h * h))
        rows = []
        for line in range(cut_y, min(full_h, cut_y + cut_h)):
            start = (line * full_w + cut_x) * 3
            rows.append(bgr[start:start + cut_w * 3])
        return {"ok": True, "error": "", "bgr": b"".join(rows), "width": cut_w, "height": cut_h,
                "source": "print" if use_print else "screen"}
    return {"ok": False, "error": "capture-failed"}


def save_png(path: str | Path, bgr: bytes, width: int, height: int) -> bool:
    """把截图存成 PNG 供界面框选用（有 Pillow 才存，缺了返回 False）。"""
    try:
        from PIL import Image
    except Exception:
        return False
    try:
        img = Image.frombytes("RGB", (width, height), bgr, "raw", "BGR")
        img.save(str(path))
        return True
    except Exception:
        return False
