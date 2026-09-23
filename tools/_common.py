"""tools/ 下脚本的公共入口：控制台自保 + 数据目录解析。

一次修掉两个踩过的坑：

1. **中文控制台 + 界面文案里的「⋯」**：`print` 在 cp936 下直接抛
   UnicodeEncodeError。实测 `tools/e2e.py` 跑到第 81 步（翻译面板状态行里带「⋯」）
   整批中断，与 README 的「95/95」对不上 —— 只要加了 `PYTHONUTF8=1` 才是 95/95。
   CI 恰好设了这个环境变量，所以线上一直没暴露。
2. **P2 数据分账后的库路径**：库已经在 `data/state/`，但一堆探针还写死
   `data/library.json`，开箱就是 FileNotFoundError（`check_library` / `vntext_live` /
   `vntext_hookprobe` / `vntext_rawdump` 实测全崩）。

所以：控制台一律走 `setup_console()`；数据路径一律问应用自己的 `Layout`，不再各自拼字符串 ——
以后数据布局再变，探针跟着一起变。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 本来就能打出中文的编码：保持原样（改成 UTF-8 反而让中文控制台变乱码）
CJK_ENCODINGS = {"cp936", "gbk", "gb2312", "gb18030", "cp932", "shift-jis", "sjis",
                 "cp949", "euc-kr", "cp950", "big5"}


def setup_console() -> None:
    """让 `print` 不再因为编不出的字符（如界面文案里的「⋯」）整批崩掉。

    分两种控制台，谁也别吃亏：

    * **中文控制台（cp936 等）**：保持原编码、只放宽 `errors` —— 中文照常显示，
      只有「⋯」这类罕见字符退化成 `?`。硬改成 UTF-8 的话中文会全屏乱码，
      比崩得更难看；
    * **非 CJK 控制台（CI 的英文 code page、cp437/cp1252）**：切到 UTF-8。
      那里的终端本来也显示不了中文，而 CI 日志、GitHub Actions 注解都是 UTF-8，
      切过去反而看得见 —— `tests/test_ci_environment.py` 锁的就是这条。
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("_", "-")
        try:
            if encoding.startswith("utf") or encoding in CJK_ENCODINGS:
                stream.reconfigure(errors="replace")   # type: ignore[attr-defined]
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        except Exception:
            pass


def layout():
    """当前数据目录的布局（尊重 `AURORA_DATA`；每次现算，不吃缓存）。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from aurora.infra.store.paths import Layout, resolve_data_dir

    return Layout(resolve_data_dir())


def library_file() -> pathlib.Path:
    return layout().library_file


def settings_file() -> pathlib.Path:
    return layout().settings_file


def legacy_library_file() -> pathlib.Path:
    """v1 遗留库（只用来判断「这是没迁移过的老数据目录」）。"""
    return layout().legacy_library


def load_library(path: pathlib.Path | str | None = None) -> dict:
    target = pathlib.Path(path) if path else library_file()
    return json.loads(target.read_text(encoding="utf-8"))


def pick_game(library: dict, key: str) -> dict | None:
    """按名字/exe 关键字挑一个游戏；找不到返回 None。"""
    needle = str(key or "").lower()
    if not needle:
        return None
    for game in library.get("games") or []:
        hay = f"{game.get('name', '')} {game.get('exe', '')}".lower()
        if needle in hay:
            return game
    return None


def guard_webview_start(window, *, label: str, profile: pathlib.Path | str | None = None,
                        timeout: float = 60.0) -> dict:
    """给 `webview.start()` 兜底：`loaded` 不来就**别永远卡着**。

    2026-09-23 排出来的坑：WebView2 初始化会**偶发**失败（控制台一行
    `WebView2 initialization failed … 0x8007139F`），此后 `loaded` 永远不触发；
    而真机脚本的 `run()` 只挂在 `window.events.loaded` 上 —— 于是整个进程
    静默卡死（`visual.py` 连 report 都不写，看日志只有 entry 一行），
    使用者/AI 都只会觉得「工具坏了」。实测**直接重跑一次就好**，所以这里做的是
    「超时（默认 60s）→ 写一条能看懂的日志 → 退出码 3」：快失败，别静默挂死。

    **不做自动重跑**：在已经卡死的进程里 `subprocess`/`os.execv` 起子进程实测同样
    卡住（2026-09-23：四个 python 进程互相等，连日志都写不出来），比不做还糟。
    另外 `os.execv` 在 Windows 上不传递退出码（实测只跑 `os._exit(7)` 的脚本经
    execv 重跑后调用方读到 0），失败会被当成成功。

    设 `AURORA_WV_FRESH_PROFILE=1` 可先把 `profile` 目录**改名留档**
    （`<名字>.stale-<时间戳>`，改名不是删除）再启动 —— profile 坏掉时用这个。

    返回共享状态字典；`state["loaded"]` 表示 `loaded` 是否已经来过。
    """
    state = {"loaded": False, "label": label}

    def mark_loaded() -> None:
        state["loaded"] = True

    try:
        window.events.loaded += mark_loaded
    except Exception:
        pass

    def write(msg: str) -> None:
        print(f"[webview 守卫] {msg}")
        try:
            log_dir = ROOT / "_sandbox"
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%H:%M:%S")
            with (log_dir / "webview-guard.log").open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} [{label}] {msg}\n")
        except Exception:
            pass

    def stale_profile() -> None:
        if profile is None:
            return
        target = pathlib.Path(profile)
        if not target.exists():
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            target.rename(target.with_name(f"{target.name}.stale-{stamp}"))
            write(f"profile 已改名留档：{target.name} → {target.name}.stale-{stamp}")
        except OSError as exc:
            write(f"profile 改名失败：{exc}")

    if profile is not None and os.environ.get("AURORA_WV_FRESH_PROFILE"):
        stale_profile()

    def watchdog() -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            if state["loaded"]:
                return
        write(f"{label}: WebView2 的 loaded 事件 {timeout:.0f}s 内没到 —— "
              "多半是初始化偶发失败（上面应有 WebView2 initialization failed / "
              "0x8007139F）。**直接重跑一次通常就好**；"
              "连续失败就带 AURORA_WV_FRESH_PROFILE=1 再跑（会先把 profile 改名留档）。")
        write(f"{label}: 放弃（退出码 3），不静默挂死。")
        os._exit(3)

    threading.Thread(target=watchdog, daemon=True).start()
    return state


def park_cursor() -> None:
    """把鼠标挪出窗口（屏幕左上角 2,2）再截图。

    主题矩阵是**逐格比对**的：指针停在设置页的行 / 卡片上时，hover 高亮会被拍进去
    —— 2026-09-23 实测 e2e 的拖动测试把光标留在设置页，`aurora-light-settings`
    网格 [8,4] 从 `[250,251,251]` 变成 `[232,232,233]`（差 19，超过容差 12），
    同一份基线「一会儿绿一会儿红」。`el-tooltip` 那条早处理了，hover 高亮靠这一步。
    """
    try:
        import ctypes

        ctypes.WinDLL("user32").SetCursorPos(2, 2)
    except Exception:
        pass


def print_window(hwnd: int, path: pathlib.Path) -> tuple[int, int]:
    """让窗口自己画一份截图（`PrintWindow` + `PW_RENDERFULLCONTENT`）。

    为什么需要它：真机截图一直是「临时置顶 + 抓屏」，可使用者开着别的窗口时
    仍然会抓到别人的界面 —— 2026-09-23 实测过一次：对比度工具量到近黑底色（1.06），
    翻出截图才发现采样带上压着用户正跑的 galgame；同一轮主题矩阵也抓到过终端窗口。
    自绘走的是窗口自己的绘制结果，**别的窗口压在上面也不影响**，
    实测颜色与抓屏差 ~1/255（工具条区域的均值 225.6/228.9/228.5 对 227.1/230.0/229.5）。

    返回 (宽, 高)；失败返回 (0, 0)。少数驱动上可能返回黑帧，调用方要自己判断
    「这张图是不是空的」，空的就退回 `ImageGrab` 那条路。
    """
    import ctypes
    from ctypes import wintypes

    from PIL import Image

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    rc = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc)):
        return 0, 0
    width, height = rc.right - rc.left, rc.bottom - rc.top
    if width <= 0 or height <= 0:
        return 0, 0

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    hdc = user32.GetWindowDC(wintypes.HWND(hwnd))
    if not hdc:
        return 0, 0
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    try:
        gdi32.SelectObject(mem, bmp)
        # 0x2 = PW_RENDERFULLCONTENT：硬件加速 / DirectComposition 的窗口也能画出来
        if not user32.PrintWindow(wintypes.HWND(hwnd), mem, 0x00000002):
            return 0, 0
        head = BITMAPINFOHEADER()
        head.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        head.biWidth = width
        head.biHeight = -height                # 负数 = 自上而下
        head.biPlanes = 1
        head.biBitCount = 32
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(mem, bmp, 0, height, buffer, ctypes.byref(head), 0)
        Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1) \
             .convert("RGB").save(path)
        return width, height
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(wintypes.HWND(hwnd), hdc)
