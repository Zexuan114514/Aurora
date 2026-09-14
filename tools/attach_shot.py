"""抓取当前正在运行的 Aurora 窗口并检查侧边栏封面是否渲染。"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

OUT = Path(__file__).resolve().parent / "attached.png"
user32 = ctypes.WinDLL("user32", use_last_error=True)


def main() -> int:
    hwnd = user32.FindWindowW(None, "Aurora 游戏启动器")
    if not hwnd:
        print("未找到正在运行的 Aurora 窗口")
        return 1
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    time.sleep(1.0)
    rc = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))

    # 本进程不感知 DPI，拿到的是虚拟化坐标；乘上显示器缩放才是真实像素
    try:
        scale = user32.GetDpiForWindow(wintypes.HWND(hwnd)) / 96.0
    except Exception:
        scale = 1.0
    box = (int(rc.left * scale), int(rc.top * scale),
           int(rc.right * scale), int(rc.bottom * scale))
    w, h = box[2] - box[0], box[3] - box[1]
    print(f"窗口 {w}x{h} 物理像素 @ {box[0]},{box[1]}  (缩放 {scale:.2f})")

    from PIL import Image, ImageGrab, ImageStat

    img = ImageGrab.grab(bbox=box, all_screens=True)
    if img.size != (w, h):
        img = img.resize((w, h))
    img.save(OUT)

    sx, sy = w / 1356, h / 817
    print("\n侧边栏封面缩略图（CSS x 25..67）:")
    y = 131
    for i in range(6):
        box2 = (int(25 * sx), int((y + 7) * sy), int(67 * sx), int((y + 63) * sy))
        crop = img.crop(box2).convert("RGB")
        st = ImageStat.Stat(crop)
        g = ImageStat.Stat(crop.convert("L"))
        flag = "有图" if g.stddev[0] > 8 else "空白"
        print(f"  第{i + 1}行 y={y:3}  mean=({st.mean[0]:5.1f},{st.mean[1]:5.1f},{st.mean[2]:5.1f}) "
              f"sd={g.stddev[0]:5.1f}  -> {flag}")
        y += 75

    small = img.convert("L").resize((100, 40), Image.LANCZOS)
    px = small.load()
    ramp = " .:-=+*#%@"
    print("\n整窗亮度图:")
    for row in range(40):
        print("  |" + "".join(ramp[min(9, px[x, row] * 10 // 256)] for x in range(100)) + "|")
    return 0


if __name__ == "__main__":
    sys.exit(main())
