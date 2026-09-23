"""真机对比度自检：量「文字底下那条真实像素」与文字色的 WCAG 对比度。

为什么单独有这么一个工具：主题契约（tools/checks/check_theme_contract.py）只保证
「令牌补齐了」，不保证「补的值看得见」。2026-09-22 的体验反馈里就是这么翻车的 ——
深色态的面板没有底色，亮壁纸透上来变成「亮底白字」，对比度掉到 1.04，
而 e2e / visual 全绿。

用法（会短暂切换主题，跑完写回原值）：
    python tools\\contrast.py                # 全跑：4 套风格 × 深/浅 × 2 个页面
    $env:CONTRAST_OFFLINE="1"; python tools\\contrast.py   # 用离线沙盒数据（壁纸来自 CDN）

阈值取 WCAG：正文 ≥ 4.5，大字号（标题）≥ 3.0。不达标就退出码 1。
取样方法：文字块的**正下方 8px、等宽一条带**（渲染后的真实像素）当底色，
文字色取 getComputedStyle（避开抗锯齿），再按相对亮度算对比度。

2026-09-23 加了**遮挡检测**：抓屏前先用 `WindowFromPoint` 复核每个采样点是不是
真的落在 Aurora 窗口上。那天使用者正跑着 galgame，游戏窗口压在采样点上，
测出来的是游戏的黑底 —— 展签式画廊浅色态因此假红了两条（1.06 / 1.04）。
现在被盖住的点会重试置顶，仍被盖住就标成「没测到」并让退出码非 0，
既不假绿也不假红；报告里还带上采样点命中的页面元素（elementsFromPoint），
用来区分「压在立绘上」和「真的没有兜底」。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import guard_webview_start, park_cursor, setup_console  # noqa: E402

setup_console()

import ctypes  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from ctypes import wintypes  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox"
TEST_DATA = SANDBOX / "contrast-data"
OUT = SANDBOX / "contrast-shots"
REPORT = ROOT / "tools" / "contrast-report.json"

if os.environ.get("CONTRAST_OFFLINE"):
    os.environ["AURORA_DATA"] = str(TEST_DATA)

import webview  # noqa: E402

import main as app_main  # noqa: E402
from gl.api import Api  # noqa: E402

STYLES = ("aurora", "gallery", "screening", "shelf")
MODES = ("dark", "light")
BODY_MIN = 4.5          # 正文
LARGE_MIN = 3.0         # 大字号（标题 / 说明性的小字我们不按大字号算）

#: (页面, 文字名, 取提示文字色，取样用的元素)
TARGETS = {
    "settings": (
        ("设置页·小标题", "#settingsView .set-pane.on h3", LARGE_MIN),
        ("设置页·说明文字", "#settingsView .set-pane.on .set-note", BODY_MIN),
    ),
    "game": (
        ("游戏页·标题", "#gTitle", LARGE_MIN),
        ("游戏页·简介", "#gDesc", BODY_MIN),
    ),
}


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    rc = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    return rc.left, rc.top, rc.right, rc.bottom


def raise_window(hwnd: int) -> None:
    """把主窗钉到最前（实测过游戏窗口压在主窗上，抓到的就是游戏界面）。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    HWND_TOPMOST = -1
    SWP = 0x0001 | 0x0002 | 0x0010          # NOSIZE | NOMOVE | NOACTIVATE
    hwnd_w = wintypes.HWND(hwnd)
    user32.SetWindowPos(hwnd_w, HWND_TOPMOST, 0, 0, 0, 0, SWP)
    user32.SetForegroundWindow(hwnd_w)
    user32.BringWindowToTop(hwnd_w)


def blocked_points(hwnd: int, rect: tuple[int, int, int, int],
                   points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """采样点（截图里的坐标）里，哪些被**别的窗口**盖住了。

    返回屏幕坐标列表。`WindowFromPoint` 会连子窗口一起命中，所以 WebView2 的
    子窗口算「自己的」；根窗口不是主窗就说明这块像素不属于 Aurora。
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    GA_ROOT = 2
    out: list[tuple[int, int]] = []
    for x, y in points:
        sx, sy = rect[0] + int(round(x)), rect[1] + int(round(y))
        found = user32.WindowFromPoint(wintypes.POINT(sx, sy))
        if not found:
            continue
        if user32.GetAncestor(wintypes.HWND(found), GA_ROOT) != hwnd:
            out.append((sx, sy))
    return out


def capture(hwnd: int, path: Path, points: list[tuple[float, float]] = (),
            tries: int = 4) -> tuple[int, int, list[tuple[int, int]], bool]:
    """直接抓屏后裁窗口区域。

    `points` 是这张图上要取样的位置（图坐标）：抓之前先确认它们没被别的窗口压住，
    被压住就重新置顶再试；重试完还压着就把这些点原样报回去（调用方标成「没测到」）。
    真被压住时最后一招是让窗口自绘（`_common.print_window`）—— 它不受遮挡，
    但颜色会差 ~1/255，所以只在前面的路都走不通时用，并在报告里标出来。
    返回值最后一位表示「这张图是自绘的」。
    """
    park_cursor()      # 指针停在控件上会带 hover 高亮，采样的底色就不是常规态
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    HWND_NOTOPMOST = -2
    SWP = 0x0001 | 0x0002 | 0x0010          # NOSIZE | NOMOVE | NOACTIVATE
    blocked: list[tuple[int, int]] = []
    for attempt in range(max(1, tries)):
        raise_window(hwnd)
        time.sleep(0.6 if attempt == 0 else 0.5)
        rect = window_rect(hwnd)
        blocked = blocked_points(hwnd, rect, list(points))
        if not blocked:
            break
    if blocked and points:                     # 压着就自绘一份，比「没测到」强
        from PIL import Image, ImageStat

        from _common import print_window

        if print_window(hwnd, path)[0] > 0 and path.is_file():
            gray = ImageStat.Stat(Image.open(path).convert("L"))
            if gray.mean[0] > 6 or gray.stddev[0] > 4:
                return Image.open(path).width, Image.open(path).height, [], True
    rect = window_rect(hwnd)
    from PIL import ImageGrab

    img = ImageGrab.grab(bbox=rect, all_screens=True)
    img.save(path)
    user32.SetWindowPos(wintypes.HWND(hwnd), HWND_NOTOPMOST, 0, 0, 0, 0, SWP)
    # 报告里给的是「图坐标」，调用方不必再关心窗口在屏幕上的位置
    local = [(sx - rect[0], sy - rect[1]) for sx, sy in blocked]
    return img.width, img.height, local, False


def rel_lum(rgb) -> float:
    def channel(value: float) -> float:
        value = value / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2])


def contrast(fg, bg) -> float:
    a, b = rel_lum(fg), rel_lum(bg)
    return round((max(a, b) + 0.05) / (min(a, b) + 0.05), 2)


def strip_mean(path: Path, box_css, scale: float):
    """文字块下方 8px、等宽的一条带（元素 rect 是 CSS 像素，截图是物理像素）。"""
    from PIL import Image, ImageStat

    img = Image.open(path).convert("RGB")
    x0 = int(box_css[0] * scale)
    y0 = int((box_css[1] + box_css[3] + 8) * scale)
    x1 = int((box_css[0] + box_css[2]) * scale)
    y1 = y0 + max(4, int(8 * scale))
    crop = img.crop((max(0, x0), max(0, y0), min(img.width, x1), min(img.height, y1)))
    mean = ImageStat.Stat(crop).mean
    return (mean[0], mean[1], mean[2])


def physical_scale(hwnd: int, window) -> float:
    """截图（物理像素）与 CSS 像素的比值：元素 rect 是 CSS 像素，要先乘这个数。"""
    left, _, right, _ = window_rect(hwnd)
    inner = float(window.evaluate_js("window.innerWidth")) or 1.0
    return (right - left) / inner


def rect(window, selector: str):
    raw = window.evaluate_js(f"""(() => {{
      const node = document.querySelector({json.dumps(selector)});
      if (!node) return '';
      const r = node.getBoundingClientRect();
      return JSON.stringify([r.x, r.y, r.width, r.height]);
    }})()""")
    return json.loads(raw) if raw else None


def hits(window, x: float, y: float) -> list[str]:
    """采样点命中的页面元素（从最上层往下数 4 个）——用来区分「压在立绘上」
    和「真的没有兜底」。"""
    raw = window.evaluate_js(f"""(() => {{
      return JSON.stringify([...document.elementsFromPoint({x}, {y})].slice(0, 4)
        .map((n) => n.tagName.toLowerCase() + (n.id ? '#' + n.id : '')
          + (typeof n.className === 'string' && n.className.trim()
             ? '.' + n.className.trim().split(/\\s+/).slice(0, 2).join('.') : '')));
    }})()""") or "[]"
    return json.loads(raw)


def color(window, selector: str):
    raw = window.evaluate_js(f"""(() => {{
      const node = document.querySelector({json.dumps(selector)});
      return node ? getComputedStyle(node).color : '';
    }})()""") or ""
    parts = [float(part) for part in raw.replace("rgba(", "").replace("rgb(", "")
             .rstrip(")").split(",")[:3]]
    return tuple(parts) if len(parts) == 3 else None


def apply_theme(window, style: str, mode: str) -> None:
    window.evaluate_js(f"""(() => {{
      const s = document.getElementById('setThemeStyle');
      s.value = {json.dumps(style)};
      s.dispatchEvent(new Event('change', {{bubbles: true}}));
    }})()""")
    time.sleep(0.8)
    window.evaluate_js(f"""(() => {{
      const t = document.getElementById('setTheme');
      t.value = {json.dumps(mode)};
      t.dispatchEvent(new Event('change', {{bubbles: true}}));
    }})()""")
    time.sleep(1.2)
    for _ in range(20):                     # 提示条会压在画面上，等它退场
        busy = window.evaluate_js(
            "!!(document.getElementById('toast')||{}).classList?.contains('show')")
        if not busy:
            return
        time.sleep(0.3)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("CONTRAST_OFFLINE"):
        shutil.rmtree(TEST_DATA, ignore_errors=True)
        TEST_DATA.mkdir(parents=True, exist_ok=True)

    api = Api()
    original = {key: api._library.settings.get(key)
                for key in ("theme", "theme_mode", "palette")}
    window = app_main.build_window(api)
    api._window = window
    report: dict = {"original": original, "rows": [], "errors": []}
    started = {"done": False}

    def samples(window, page: str, scale: float) -> list[dict]:
        """每个取样文字块：CSS 里的 rect + 图上那条「正下方 8px」的位置。"""
        out: list[dict] = []
        for label, selector, floor in TARGETS[page]:
            box = rect(window, selector)
            fg = color(window, selector)
            if not box or not fg:
                continue
            x0, y0 = box[0] * scale, (box[1] + box[3] + 8) * scale
            x1, y1 = (box[0] + box[2]) * scale, y0 + max(4, int(8 * scale))
            out.append({"label": label, "selector": selector, "floor": floor,
                        "fg": fg, "box": box, "strip": (x0, y0, x1, y1),
                        "points": [(x0 + (x1 - x0) * t, (y0 + y1) / 2)
                                   for t in (0.15, 0.5, 0.85)]})
        return out

    def measure(window, shot: Path, scale: float, page: str, style: str, mode: str,
                rows: list[dict], blocked: list[tuple[int, int]],
                self_drawn: bool = False) -> None:
        for row in rows:
            box, (x0, y0, x1, y1) = row["box"], row["strip"]
            covered = [pt for pt in blocked
                       if x0 - 1 <= pt[0] <= x1 + 1 and y0 - 1 <= pt[1] <= y1 + 1]
            bg = strip_mean(shot, box, scale)
            value = contrast(row["fg"], bg)
            entry = {
                "page": page, "style": style, "mode": mode, "text": row["label"],
                "fg": [round(v) for v in row["fg"]], "bg": [round(v) for v in bg],
                "contrast": value, "min": row["floor"],
                # 采样点命中什么元素：压在立绘上（元素是 .bg-img / img）与「没有兜底」
                # 是两回事，报告里要分得开（见 feedback 的遗留小节）
                "hit": hits(window, box[0] + box[2] / 2, box[1] + box[3] + 12),
            }
            if self_drawn:
                # 自绘抓的：颜色差 ~1/255，标出来供核对
                entry["capture"] = "printwindow"
            if covered:
                # 被别的窗口盖住时算出来的底色不是 Aurora 画的，宁可不测也不假红 / 假绿
                entry["ok"] = None
                entry["tainted"] = covered
            else:
                entry["ok"] = value >= row["floor"]
            report["rows"].append(entry)

    def run() -> None:
        if started["done"]:
            return
        started["done"] = True
        time.sleep(6)
        try:
            hwnd = app_main.winapi.handle_of(window)
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.2)
            window.evaluate_js(
                "document.querySelector('#setNav .set-tab[data-pane=look]').click()")
            time.sleep(0.8)

            for style in STYLES:
                for mode in MODES:
                    apply_theme(window, style, mode)
                    shot = OUT / f"{style}-{mode}-settings.png"
                    scale = physical_scale(hwnd, window)
                    rows = samples(window, "settings", scale)
                    width, _, blocked, self_drawn = capture(
                        hwnd, shot, [pt for row in rows for pt in row["points"]])
                    measure(window, shot, width / float(window.evaluate_js("window.innerWidth")),
                            "settings", style, mode, rows, blocked, self_drawn)

            window.evaluate_js("document.getElementById('setBack').click()")
            time.sleep(1.0)
            window.evaluate_js("document.querySelector('.vs-btn[data-view=home]').click()")
            time.sleep(1.2)
            # 单击封面是「进游戏页」，双击会**启动游戏**（沙盒里的 ping.exe 副本）——
            # 启动了就会多一条「运行中」徽标和计时器，深色/浅色两轮之间还会变，
            # 采样点跟着上下浮动。只进页，不启动。
            window.evaluate_js("""(() => {
              const tile = document.querySelector('#hallRow .gi.focus[data-id]')
                || document.querySelector('#hallRow .gi[data-id]');
              if (tile) tile.dispatchEvent(new MouseEvent('click', {bubbles: true}));
            })()""")
            time.sleep(2.0)
            for style in STYLES:
                for mode in MODES:
                    apply_theme(window, style, mode)
                    shot = OUT / f"{style}-{mode}-game.png"
                    scale = physical_scale(hwnd, window)
                    rows = samples(window, "game", scale)
                    width, _, blocked, self_drawn = capture(
                        hwnd, shot, [pt for row in rows for pt in row["points"]])
                    measure(window, shot, width / float(window.evaluate_js("window.innerWidth")),
                            "game", style, mode, rows, blocked, self_drawn)
        except Exception:                                     # noqa: BLE001
            import traceback

            report["errors"].append(traceback.format_exc()[-500:])
        finally:
            try:                                              # 主题写回原值
                window.evaluate_js(f"""(() => {{
                  const s = document.getElementById('setThemeStyle');
                  const t = document.getElementById('setTheme');
                  if (s) {{ s.value = {json.dumps(original.get('theme') or 'aurora')};
                            s.dispatchEvent(new Event('change', {{bubbles: true}})); }}
                  if (t) {{ t.value = {json.dumps(original.get('theme_mode') or 'dark')};
                            t.dispatchEvent(new Event('change', {{bubbles: true}})); }}
                }})()""")
                time.sleep(1.2)
                # 还原必须**真的落盘**再退：存储是「去抖 + 后台写线程」，
                # 下面的 `os._exit` 会把还没写的还原丢掉 —— 2026-09-23 实测
                # 跑完这个工具之后使用者的设置被留在 gallery-light。
                api._library.flush()
            except Exception:                                 # noqa: BLE001
                pass
            bad = [row for row in report["rows"] if row["ok"] is False]
            tainted = [row for row in report["rows"] if row["ok"] is None]
            report["failed"] = [f"{row['style']}-{row['mode']} {row['text']}"
                                f" {row['contrast']} < {row['min']}" for row in bad]
            report["tainted"] = [f"{row['style']}-{row['mode']} {row['text']}"
                                 f"（采样点被别的窗口盖住）" for row in tainted]
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            print(f"\n{'组合':<20}{'文字':<18}{'对比度':>7}{'下限':>6}  底色 / 采样点命中")
            for row in report["rows"]:
                flag = "  " if row["ok"] else ("✗ " if row["ok"] is False else "? ")
                print(f"{flag}{row['style'] + '-' + row['mode']:<18}{row['text']:<18}"
                      f"{row['contrast']:>7}{row['min']:>6}  {row['bg']} / "
                      + ", ".join(row.get("hit") or [])[:52])
            print(f"\n不达标 {len(bad)} 项，没测到 {len(tainted)} 项 -> {REPORT.relative_to(ROOT)}")
            for row in report["failed"]:
                print("   ✗", row)
            for row in report["tainted"]:
                print("   ?", row, "—— 把别的窗口收起来再跑一次")
            try:
                window.destroy()
            except Exception:                                 # noqa: BLE001
                pass
            sys.stdout.flush()
            # pywebview 在 Windows 上销毁窗口后事件循环偶尔不返回（实测过进程挂住），
            # 报告已经落盘、结果也打完了，直接退，别让维护者以为卡死。
            os._exit(1 if (bad or tainted) else 0)

    window.events.loaded += lambda: threading.Thread(target=run, daemon=True).start()
    guard_webview_start(window, label="contrast",
                        profile=Path(os.environ.get("AURORA_DATA")
                                     or app_main.config.WEB_DATA_DIR) / "webview")
    webview.start(gui="edgechromium", private_mode=False, http_port=app_main.free_port(),
                  storage_path=str(Path(os.environ.get("AURORA_DATA") or
                                        app_main.config.WEB_DATA_DIR) / "webview"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
