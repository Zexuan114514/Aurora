"""启动应用 -> 注入可选 JS -> 窗口内截图 -> 量化分析，一条龙自检。

用法:
  python tools/snap.py                    # 默认截图 + 分析
  $env:SNAP_JS="..." ; python tools/snap.py
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

import main as app_main  # noqa: E402
from gl.api import Api  # noqa: E402

OUT = Path(__file__).resolve().parent
SHOT = OUT / "shot.png"


def capture(hwnd: int, path: Path) -> tuple[int, int]:
    """直接抓屏后裁剪窗口区域：PrintWindow 会衰减颜色，不可用于取色。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    time.sleep(0.5)

    rc = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top

    from PIL import ImageGrab

    img = ImageGrab.grab(bbox=(rc.left, rc.top, rc.right, rc.bottom), all_screens=True)
    if img.size != (w, h):
        img = img.resize((w, h))
    img.save(path)
    return w, h


def main() -> int:
    api = Api()
    window = app_main.build_window(api)
    api._window = window

    def run() -> None:
        time.sleep(float(os.environ.get("SNAP_DELAY", "6")))
        info = {}
        try:
            js = os.environ.get("SNAP_JS")
            if js:
                res = window.evaluate_js(f"(() => {{ {js} }})()")
                info["inject"] = res
                time.sleep(float(os.environ.get("SNAP_SETTLE", "1.6")))
            hwnd = app_main.winapi.handle_of(window)
            size = capture(hwnd, SHOT)
            info["capture"] = list(size)
            (OUT / "snap-report.json").write_text(
                json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            print("captured", size)
        except Exception as exc:
            print("snap failed:", exc)
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    window.events.loaded += lambda: threading.Thread(target=run, daemon=True).start()
    webview.start(gui="edgechromium", private_mode=False, http_port=app_main.free_port(),
                  storage_path=str(app_main.config.WEB_DATA_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
