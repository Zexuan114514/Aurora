"""视觉自检：大厅封面 + 背景选择面板缩略图是否真的渲染出来了。"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import guard_webview_start, park_cursor, print_window, setup_console  # noqa: E402

setup_console()

import ctypes
import json
import os
import shutil
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox"
TEST_DATA = SANDBOX / "visual-data"
os.environ["AURORA_DATA"] = str(TEST_DATA)

import webview  # noqa: E402

import main as app_main  # noqa: E402
from gl.api import Api  # noqa: E402

OUT = Path(__file__).resolve().parent
GAMES = [
    ("ELDEN RING", "Game", "eldenring.exe"),
    ("Cyberpunk 2077", "bin/x64", "Cyberpunk2077.exe"),
    ("Hollow Knight", "", "Hollow Knight.exe"),
]

CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps"
BAD = "https://invalid.example.invalid/nope.jpg"


def offline_records() -> list[dict]:
    """不走 Steam 接口，直接用已知可用的 CDN 地址构造测试数据。"""
    out = []
    for index, appid in enumerate((1245620, 1091500, 367520)):
        img = lambda name: f"{CDN}/{appid}/{name}"
        out.append({
            "id": f"offline{index}",
            "exe": str(SANDBOX / "visual-games" / GAMES[index][0] / GAMES[index][1] /
                       GAMES[index][2]),
            "name": GAMES[index][0],
            "exe_stem": GAMES[index][2].rsplit(".", 1)[0],
            "dir_name": GAMES[index][0],
            "metadata_state": "ok",
            "appid": appid,
            # 第一个故意是坏链接，用来验证前端回退链
            "cover": BAD,
            "cover_sources": [BAD, img("library_600x900.jpg"), img("capsule_616x353.jpg")],
            "logo": img("logo.png"),
            "background": img("library_hero.jpg"),
            "background_kind": "hero",
            "images": [
                {"url": img("library_hero.jpg"), "kind": "hero", "label": "官方封面图",
                 "thumb": img("library_hero.jpg")},
                {"url": img("library_hero_blur.jpg"), "kind": "hero", "label": "官方封面图 · 柔焦",
                 "thumb": img("library_hero_blur.jpg")},
                {"url": img("page_bg_generated_v6b.jpg"), "kind": "hero", "label": "商店页面背景",
                 "thumb": img("page_bg_generated_v6b.jpg")},
                {"url": img("capsule_616x353.jpg"), "kind": "art", "label": "商店背景",
                 "thumb": img("capsule_616x353.jpg")},
                {"url": BAD, "kind": "art", "label": "坏链接（应显示占位）", "thumb": BAD},
                {"url": img("header.jpg"), "kind": "header", "label": "头图",
                 "thumb": img("header.jpg")},
            ],
        })
    return out


def capture_screen(hwnd: int, path: Path) -> tuple[int, int]:
    """抓屏（临时置顶 + `ImageGrab`）——自绘失败时的退路。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    SWP = 0x0001 | 0x0002 | 0x0010            # NOSIZE | NOMOVE | NOACTIVATE
    user32.SetWindowPos(wintypes.HWND(hwnd), -1, 0, 0, 0, 0, SWP)   # HWND_TOPMOST
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    time.sleep(0.6)
    rc = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    from PIL import ImageGrab

    img = ImageGrab.grab(bbox=(rc.left, rc.top, rc.right, rc.bottom), all_screens=True)
    if img.size != (w, h):
        img = img.resize((w, h))
    img.save(path)
    user32.SetWindowPos(wintypes.HWND(hwnd), -2, 0, 0, 0, 0, SWP)   # HWND_NOTOPMOST
    return w, h


def capture(hwnd: int, path: Path) -> tuple[int, int]:
    """抓窗口区域：**先让窗口自己画**，画不出来再退回抓屏。

    自绘（`PrintWindow` + `PW_RENDERFULLCONTENT`，见 `_common.print_window`）不受
    其它窗口遮挡 —— 以前是「临时置顶 + 抓屏」，但使用者一开着浏览器 / 终端 /
    游戏，抓到的就是别人的界面（2026-09-23 实测抓到过终端窗口，还被当成主题回归）。
    少数驱动上自绘会返回黑帧，所以这里查一下「是不是空的」，是空的就走抓屏那条老路
    （它至少会临时置顶，且真机上一直能用）。
    抓之前先把鼠标挪出窗口：指针停在控件上会留下 hover 高亮，逐格比对时就是一条
    假偏差（见 `_common.park_cursor`）。
    """
    from PIL import Image, ImageStat

    park_cursor()
    size = print_window(hwnd, path)
    if size[0] > 0 and path.is_file():
        gray = ImageStat.Stat(Image.open(path).convert("L"))
        if gray.mean[0] > 6 or gray.stddev[0] > 4:
            return size
    return capture_screen(hwnd, path)


def cell_stats(img, box):
    from PIL import ImageStat

    crop = img.crop(box).convert("RGB")
    st = ImageStat.Stat(crop)
    gs = ImageStat.Stat(crop.convert("L"))
    return {
        "mean": [round(x, 1) for x in st.mean],
        "lum": round(gs.mean[0], 1),
        "sd": round(gs.stddev[0], 1),
    }


# ---------------------------------------------------------------
# 主题矩阵：四套风格 × 深/浅
#
# 分级截图基线（ADR-0013 说好的「深色 4 套 × 5 界面 + 浅色默认主题 5 张」）：
# 每个主题截 5 个界面，指纹取 16×10 网格的平均色，按容差比 —— 不做逐像素比对。
# 主题改的是整块面板 / 文字 / 强调色，网格均值足够抓回归，又不会被一两个像素带偏。
#
# 基线文件：tools/baselines/theme-baseline.json（随源码入库，纯 Python 检查校验形状）。
# 重录：VISUAL_UPDATE_THEME_BASELINE=1 python tools\visual.py
# ---------------------------------------------------------------
THEME_MATRIX = (
    ("aurora", "dark"),
    ("gallery", "dark"),
    ("screening", "dark"),
    ("shelf", "dark"),
    ("aurora", "light"),
    ("atelier", "dark"),
    ("atelier", "light"),
)
THEME_SCREENS = ("hall", "game", "categories", "settings", "panel")
THEME_GRID = (16, 10)
THEME_TOLERANCE = 12
THEME_BASELINE = Path(__file__).resolve().parent / "baselines" / "theme-baseline.json"
THEME_SHOTS = SANDBOX / "theme-shots"

#: 截图前注入：图片素材（`<img>` 与背景层的 CSS background）一律隐藏
#: —— 素材加载没加载由封面 / 缩略图判据负责，主题基线不该受网络影响；
#: 动画与过渡停掉（Ken Burns 与环形过渡本来就会让两帧像素不同）；
#: 提示条也藏掉 —— 它是瞬态的，而且切主题正好会弹一条，录进基线就会抖。
#: 背景的暗化 / 渐晕层（#bg-scrim / #bg-vignette）属于主题本身，留着不藏。
#: 缩略图上的「无法预览」占位也跟着藏：它挂的是加载成功与否，网络抖一下就换脸
#: （缩略图本身是不是 broken 由封面 / 缩略图判据负责）。
#: 鼠标停在工具条某个按钮上时 `el-tooltip` 弹出来的浮层也要藏 —— 真机上指针位置
#: 每次都不一样，不藏就会偶发地多出一块浅色矩形（实测有一次基线就是这么飘的）。
THEME_FREEZE = """
(() => {
  if (document.getElementById('theme-freeze')) return 'ok';
  const style = document.createElement('style');
  style.id = 'theme-freeze';
  style.textContent = 'img,.bg-img{visibility:hidden !important}'
    + '.bg-item i{visibility:hidden !important}'
    + '#toast{visibility:hidden !important}'
    + '.el-popper{visibility:hidden !important}'
    + '*,*::before,*::after{animation:none !important;transition:none !important}';
  document.head.appendChild(style);
  return 'ok';
})()
"""

#: 先把界面恢复到「大厅 + 浮层都关掉」，再往目标页走。
#: 之前是「上一步点哪、这一步假设在哪」，只要有一处没到位，后面整组截图全错位 ——
#: 而且录基线时错位会被当成正常外观录进去，最难查。
THEME_RESET = """(() => {
  const open = (node) => !!node && !node.hidden && node.offsetParent !== null;
  const bgPanel = document.getElementById('bgPanel');
  if (bgPanel && bgPanel.classList.contains('open')) {
    document.getElementById('bgClose').click();
  }
  const settings = document.getElementById('settingsView');
  if (open(settings)) document.getElementById('setBack').click();
  if (document.body.classList.contains('page-game')) {
    const back = document.getElementById('btnBack');
    if (back && !back.hidden) back.click();
  }
  const home = document.querySelector('.vs-btn[data-view=home]');
  if (home && !home.disabled) home.click();
  return 'ok';
})()"""

THEME_STEPS = {
    "hall": "",
    # 单击封面 = 进游戏页；**双击 = 启动游戏**。原来这里用的是双击，于是录基线的同时
    # 把沙盒里的 ping.exe 副本启动了起来：游戏页多一个「运行中 · 00:00」徽标、
    # 底栏多一条「已玩 x 分钟」，下一轮跑时进程早退出了 —— 同一套主题两次指纹对不上
    # （实测 aurora-dark-game 网格[1,7] 差 69，整整一格从黑变成标题）。
    # 只为「进页」就别启动游戏，改成单击；顺带不往沙盒库里塞假会话。
    "game": """(() => {
      const tile = document.querySelector('#hallRow .gi.focus[data-id]')
        || document.querySelector('#hallRow .gi[data-id]');
      if (tile) tile.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    })()""",
    "categories": "document.querySelector('.vs-btn[data-view=categories]').click()",
    "settings": ("document.querySelector('#setNav .set-tab[data-pane=look]').click();"
                 "document.getElementById('btnSettings').click()"),
    "panel": "document.getElementById('btnBackgrounds').click()",
}

#: 截图前确认「确实停在该页」，否则重试一次；对不上就记进 unready，绝不录进基线。
THEME_READY = {
    "hall": "!document.body.classList.contains('page-game')"
            " && !document.getElementById('hall').hidden",
    "game": "document.body.classList.contains('page-game')",
    "categories": "!document.getElementById('categoriesView').hidden",
    "settings": "!document.getElementById('settingsView').hidden",
    "panel": "document.getElementById('bgPanel').classList.contains('open')",
}


def theme_apply(window, style: str, mode: str, timeout: float = 8.0) -> dict:
    """用设置页的两个下拉切主题 —— 走用户的路径，不是直接改 data-* 属性。

    风格与明暗分两次切、各自的生效都等确认：两个下拉是两次 `set_setting`，
    挤在同一个 tick 里下发时桥接偶尔只落一半（实测过一次「风格换了、明暗没换」，
    那次录出来的基线整列都是错的）。切不动的主题宁可跳过，也不写进基线。
    """
    def dataset() -> dict:
        raw = window.evaluate_js(
            "JSON.stringify({style: document.documentElement.dataset.style,"
            " theme: document.documentElement.dataset.theme})")
        return json.loads(raw or "{}")

    def wait_for(key: str, want: str) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if dataset().get(key) == want:
                return True
            time.sleep(0.3)
        return False

    window.evaluate_js(f"""(() => {{
      const s = document.getElementById('setThemeStyle');
      if (!s) return false;
      s.value = {json.dumps(style)};
      s.dispatchEvent(new Event('change', {{bubbles: true}}));
      return true;
    }})()""")
    style_ok = wait_for("style", style)

    window.evaluate_js(f"""(() => {{
      const t = document.getElementById('setTheme');
      if (!t) return false;
      t.value = {json.dumps(mode)};
      t.dispatchEvent(new Event('change', {{bubbles: true}}));
      return true;
    }})()""")
    mode_ok = wait_for("theme", mode)
    seen = dataset()
    seen["ok"] = bool(style_ok and mode_ok)
    return seen


def theme_fingerprint(path: Path) -> dict:
    """把一张截图压成网格平均色 + 整体亮度 / 对比度。"""
    from PIL import Image, ImageStat

    img = Image.open(path).convert("RGB")
    cols, rows = THEME_GRID
    cw, ch = img.width / cols, img.height / rows
    cells: list[list[int]] = []
    for row in range(rows):
        for col in range(cols):
            box = (int(col * cw), int(row * ch),
                   int((col + 1) * cw), int((row + 1) * ch))
            cells.append([round(value) for value in ImageStat.Stat(img.crop(box)).mean])
    gray = ImageStat.Stat(img.convert("L"))
    return {
        "size": [img.width, img.height],
        "cells": cells,
        "lum": round(gray.mean[0], 1),
        "sd": round(gray.stddev[0], 1),
    }


def theme_delta(base: dict, now: dict) -> tuple[int, list[int] | None]:
    """两张指纹的最大单格偏差（0-255）与出格的位置。"""
    if not base or base.get("size") != now.get("size"):
        return 999, None
    worst, where = 0, None
    for index, (old, new) in enumerate(zip(base.get("cells") or [], now.get("cells") or [])):
        delta = max(abs(a - b) for a, b in zip(old, new))
        if delta > worst:
            worst = delta
            where = [index % THEME_GRID[0], index // THEME_GRID[0]]
    return worst, where


def theme_spread(shots: dict, screens: tuple[str, ...], mode: str = "dark") -> dict:
    """四套深色风格两两之间的平均色差（0–255）——「区分度」的量化口径。

    用现成的指纹算：同一界面、两套风格，逐格逐通道取绝对差，再对格子与界面求平均。
    深浅两态之间是 200 上下（另算），四套风格之间如果只有个位数，用户感知到的
    「换主题」就只是换了个强调色（2026-09-22 的体验反馈第 2 条）。
    目标线：≥ 20（见 docs/frontend-ux-feedback.md）。P8.6 起**判红** ——
    皮肤已经改到位（实测 20.4），这条下限就是防止以后又退回「换个强调色」。
    """
    styles = [style for style, row_mode in THEME_MATRIX if row_mode == mode]
    pairs: list[dict] = []
    for index, left in enumerate(styles):
        for right in styles[index + 1:]:
            per_screen: list[float] = []
            for screen in screens:
                a = shots.get(f"{left}-{mode}-{screen}") or {}
                b = shots.get(f"{right}-{mode}-{screen}") or {}
                if not a.get("cells") or not b.get("cells"):
                    continue
                deltas = [abs(x - y) for ca, cb in zip(a["cells"], b["cells"])
                          for x, y in zip(ca, cb)]
                per_screen.append(sum(deltas) / len(deltas))
            pairs.append({
                "pair": f"{left} vs {right}",
                "mean": round(sum(per_screen) / len(per_screen), 1) if per_screen else None,
                "max": round(max(per_screen), 1) if per_screen else None,
            })
    # 深浅两态作为参照：同一套风格、不同明暗
    light_ref: list[float] = []
    for screen in screens:
        a = shots.get(f"aurora-dark-{screen}") or {}
        b = shots.get(f"aurora-light-{screen}") or {}
        if not a.get("cells") or not b.get("cells"):
            continue
        deltas = [abs(x - y) for ca, cb in zip(a["cells"], b["cells"])
                  for x, y in zip(ca, cb)]
        light_ref.append(sum(deltas) / len(deltas))
    values = [row["mean"] for row in pairs if row["mean"] is not None]
    mean = round(sum(values) / len(values), 1) if values else None
    target = 20
    return {
        "pairs": pairs,
        "mean": mean,
        "light_dark_ref": round(sum(light_ref) / len(light_ref), 1) if light_ref else None,
        "target": target,
        "ok": None if mean is None else mean >= target,
    }


def theme_capture_sane(path: Path, mode: str) -> bool:
    """截出来的图得跟明暗对得上。

    实测过一次：`data-theme` 已经是 light，画面却还是上一套深色 ——
    录基线时这种「换主题没画完」的帧会被当成正常外观录进去，之后就再也修不回来了。

    分界取 **85**：四套老主题的深色态是 9–49，浅色态 190–250，中间留了很宽的空档；
    而 Atelier（第 5 套）的深色态是「开着台灯的工作台」，实测 **60–74** —— 用原来的
    70 当分界会把它的 categories（73.7）当成「明暗没画完」反复重拍、最后整张跳过。
    这条自检要抓的是「卡在上一套深浅里」，85 仍然离浅色态（≥190）很远。
    """
    from PIL import ImageStat
    from PIL.Image import open as open_image

    lum = ImageStat.Stat(open_image(path).convert("L")).mean[0]
    return lum > 85 if mode == "light" else lum < 85


def theme_wait_ring_settled(window, timeout: float = 4.0) -> bool:
    """等环形队列的浮动画完再截图。

    那层浮动是 JS（requestAnimationFrame）插值出来的，CSS 的 animation/transition
    冻结管不着它；而面板是半透明的，背景里封面差几个像素，面板那块的平均色就会飘
    （实测：只用 CSS 冻结时，panel 这张在几套主题上稳定差 20 上下）。
    判据取「连续两次采样不再变化」——比阈值更省事，也不用猜 float 的目标值。
    """
    last = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = window.evaluate_js("""(() => {
          const api = window.__aurora;
          const ring = api && api.ring ? api.ring() : null;
          return ring ? JSON.stringify({f: ring.float, t: ring.target}) : "null";
        })()""")
        if raw in (None, "", "null"):
            return False
        now = json.loads(raw)
        state = (round(float(now.get("f") or 0), 2), round(float(now.get("t") or 0), 2))
        if state == last:
            return True
        last = state
        time.sleep(0.3)
    return False


def main() -> int:
    if TEST_DATA.exists():
        shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)
    src = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "ping.exe"
    for folder, sub, exe_name in GAMES:
        d = SANDBOX / "visual-games" / folder / sub
        d.mkdir(parents=True, exist_ok=True)
        target = d / exe_name
        if not target.exists():
            shutil.copy2(src, target)

    api = Api()
    window = app_main.build_window(api)
    api._window = window
    report: dict = {"games": [], "covers": [], "thumbs": [], "errors": []}
    started = {"done": False}

    def run() -> None:
        if started["done"]:
            return
        started["done"] = True
        time.sleep(6)
        try:
            offline = bool(os.environ.get("VISUAL_OFFLINE"))
            if offline:
                for rec in offline_records():
                    api._library.add(rec)
                    report["games"].append(rec["id"])
                # 直接写库不会触发推送，重载页面让它重新读取
                window.evaluate_js("setTimeout(() => location.reload(), 50)")
                time.sleep(9)
            else:
                for folder, sub, exe_name in GAMES:
                    path = SANDBOX / "visual-games" / folder / sub / exe_name
                    res = api.add_by_path(str(path))
                    if res.get("ok"):
                        report["games"].append(res["game"]["id"])

                # 等待元数据全部到位
                deadline = time.time() + 180
                while time.time() < deadline:
                    games = [api._library.get(g) for g in report["games"]]
                    if all(g and g.get("metadata_state") in ("ok", "notfound") for g in games):
                        break
                    time.sleep(3)

            report["meta"] = [
                {"name": g.get("name"), "state": g.get("metadata_state"),
                 "cover": g.get("cover", ""), "logo": g.get("logo", ""),
                 "images": len(g.get("images") or [])}
                for g in (api._library.get(i) for i in report["games"])
            ]

            hwnd = app_main.winapi.handle_of(window)
            w, h = capture(hwnd, OUT / "visual-list.png")
            report["size"] = [w, h]

            from PIL import Image

            img = Image.open(OUT / "visual-list.png").convert("RGB")
            sx, sy = w / 1356, h / 817

            # v2 起默认布局是「大图 + 侧列表」：环形判据前先显式切到环形队列
            # （只声明被测布局，判据数值一个没动）
            window.evaluate_js("""(() => {
              const sel = document.getElementById('setHallLayout');
              if (sel && sel.value !== 'ring') {
                sel.value = 'ring';
                sel.dispatchEvent(new Event('change'));
              }
            })()""")
            time.sleep(1.4)

            # 大厅封面：环形队列的位置 / 倾斜角 / 大小层次直接问页面要，别写死像素
            hall = json.loads(window.evaluate_js("""
              (() => {
                const out = {vw: innerWidth, tiles: []};
                document.querySelectorAll('#hallRow .gi').forEach((n) => {
                  if (!n.style.transform) return;         // 绕到背面、藏起来的那些不算
                  const r = n.getBoundingClientRect();
                  out.tiles.push({
                    key: n.dataset.id || 'add',
                    deg: Number((n.style.transform.match(/rotateY\\((-?[\\d.]+)deg/) || [0, 0])[1]),
                    x: r.x, y: r.y, w: r.width, h: r.height,
                    opacity: Number(n.style.opacity),
                  });
                });
                out.ring = window.__aurora.ring();
                return JSON.stringify(out);
              })()
            """) or "{}")
            report["ring"] = hall
            ordered = sorted(hall.get("tiles", []), key=lambda t: abs(t["deg"]))
            front = next((t for t in ordered if t["deg"] == 0), None)
            report["ring_check"] = {
                "visible": [[t["key"][:6], round(t["deg"], 1), round(t["h"], 1)]
                            for t in ordered],
                "focus_center_delta": round(
                    (front["x"] + front["w"] / 2 if front else 0) - hall.get("vw", 0) / 2, 1),
                "sizes_shrink_outwards": all(
                    a["h"] >= b["h"] - 0.5 for a, b in zip(ordered, ordered[1:])),
                "all_tilted": all(abs(t["deg"]) >= 8 for t in ordered if t["deg"]) and len(ordered) > 1,
                "front_is_biggest": bool(front) and all(front["h"] >= t["h"] for t in ordered),
            }
            for t in ordered:
                if t["x"] < 0 or t["x"] + t["w"] > hall.get("vw", 0):
                    continue          # 只统计完整落在窗口里的封面
                box = (int(t["x"] * sx), int(t["y"] * sy),
                       int((t["x"] + t["w"]) * sx), int((t["y"] + t["h"]) * sy))
                report["covers"].append(cell_stats(img, box))

            # 打开背景面板再截一张
            window.evaluate_js("document.getElementById('btnBackgrounds').click()")
            time.sleep(4)
            capture(hwnd, OUT / "visual-bg.png")
            img2 = Image.open(OUT / "visual-bg.png").convert("RGB")

            # 面板 CSS x 970..1344, 网格两列，缩略图约 170x106
            for row in range(3):
                for col in range(2):
                    x0 = 970 + col * 186 + 4
                    y0 = 118 + row * 122 + 4
                    box = (int(x0 * sx), int(y0 * sy), int((x0 + 170) * sx), int((y0 + 100) * sy))
                    report["thumbs"].append(cell_stats(img2, box))

            report["thumb_src"] = window.evaluate_js("""
              (() => {
                const out = [];
                document.querySelectorAll('.bg-item').forEach((b, i) => {
                  if (i > 6) return;
                  const img = b.querySelector('.bg-thumb img');
                  out.push({label: b.querySelector('.bg-label').textContent,
                            src: img ? img.src.slice(-46) : null,
                            broken: b.classList.contains('img-broken'),
                            natural: img ? img.naturalWidth : 0});
                });
                return JSON.stringify(out);
              })()
            """)
            report["cover_dom"] = window.evaluate_js("""
              (() => {
                const out = [];
                document.querySelectorAll('.gi-cover').forEach((c) => {
                  const img = c.querySelector('img');
                  out.push({src: img ? img.src.slice(-40) : null,
                            broken: c.classList.contains('img-broken'),
                            natural: img ? img.naturalWidth : 0});
                });
                return JSON.stringify(out);
              })()
            """)

            # ---------------- 背景缩放（只由滑杆控制） ----------------
            zoom: dict = {}
            gid = report["games"][0]
            zoom["before"] = window.evaluate_js(f"""
              (() => {{
                const g = {json.dumps(gid)};
                const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                const on = a.classList.contains('on') ? a : b;
                return JSON.stringify({{scale: {api._library.get(gid).get('bg_scale') or 1},
                                        transform: on.style.transform}});
              }})()
            """)

            # 滑杆放大到 180%
            window.evaluate_js("""
              (() => {
                const s = document.getElementById('bgZoom');
                s.value = 180;
                s.dispatchEvent(new Event('input', {bubbles: true}));
                s.dispatchEvent(new Event('change', {bubbles: true}));
                return 'zoom';
              })()
            """)
            time.sleep(1.2)
            zoom["after_slider"] = window.evaluate_js(f"""
              (() => {{
                const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                const on = a.classList.contains('on') ? a : b;
                const g = {json.dumps(gid)};
                return JSON.stringify({{scale: {api._library.get(gid).get('bg_scale') or 1},
                                        transform: on.style.transform,
                                        slider: document.getElementById('bgZoom').value}});
              }})()
            """)

            # 复位
            window.evaluate_js("document.getElementById('bgViewReset').click()")
            time.sleep(1.2)
            zoom["after_reset"] = window.evaluate_js(f"""
              (() => {{
                const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                const on = a.classList.contains('on') ? a : b;
                return JSON.stringify({{transform: on.style.transform,
                                        scale: {api._library.get(gid).get('bg_scale') or 1},
                                        slider: document.getElementById('bgZoom').value}});
              }})()
            """)
            report["zoom"] = zoom

            # ---------------- 自定义图标 ----------------
            if offline:
                icon_src = OUT / "icon-test.png"
                from PIL import Image, ImageDraw

                test_icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
                td = ImageDraw.Draw(test_icon)
                td.ellipse([8, 8, 248, 248], fill=(255, 90, 60, 255))
                td.rectangle([110, 70, 146, 186], fill=(255, 255, 255, 255))
                test_icon.save(icon_src)

                gid = report["games"][0]
                res = api._set_custom_icon(gid, icon_src)
                time.sleep(2.5)
                report["custom_icon"] = {
                    "set_ok": bool(res.get("ok")),
                    "stored": api._library.get(gid).get("custom_icon"),
                    "dom": window.evaluate_js("""
                      (() => {
                        const items = document.querySelectorAll('.gi');
                        const first = items[0] ? items[0].querySelector('.gi-cover img') : null;
                        return JSON.stringify({count: items.length,
                                               src: first ? first.src.slice(-40) : null,
                                               natural: first ? first.naturalWidth : 0});
                      })()
                    """),
                }
                api.clear_custom_icon(gid)
                time.sleep(1.5)
                report["custom_icon"]["after_clear"] = api._library.get(gid).get("custom_icon")

            # ---------------- 主题矩阵（四套风格 × 深/浅 × 5 界面） ----------------
            update_baseline = bool(os.environ.get("VISUAL_UPDATE_THEME_BASELINE"))
            THEME_SHOTS.mkdir(parents=True, exist_ok=True)
            window.evaluate_js(THEME_FREEZE)
            window.evaluate_js("""(() => {
              const sel = document.getElementById('setHallLayout');
              if (sel && sel.value !== 'ring') {
                sel.value = 'ring';
                sel.dispatchEvent(new Event('change'));
              }
            })()""")
            time.sleep(1.4)

            baseline: dict = {}
            if THEME_BASELINE.is_file():
                baseline = (json.loads(THEME_BASELINE.read_text(encoding="utf-8"))
                            .get("shots") or {})
            shots: dict = {}
            diff: list[dict] = []
            failed: list[str] = []
            unapplied: list[str] = []
            unready: list[str] = []
            for style, mode in THEME_MATRIX:
                applied = theme_apply(window, style, mode)
                if not applied.get("ok"):          # 桥接慢一拍时再等一轮
                    time.sleep(1.2)
                    applied = theme_apply(window, style, mode)
                if not applied.get("ok"):
                    unapplied.append(f"{style}-{mode}（实际 {applied.get('style')}"
                                     f"/{applied.get('theme')}）")
                    continue                        # 没切过去就整组跳过，绝不录进基线
                for screen in THEME_SCREENS:
                    window.evaluate_js(THEME_RESET)      # 先回大厅、关掉浮层
                    time.sleep(0.9)
                    ready = False
                    for attempt in range(2):             # 没到位就重来一次
                        if THEME_STEPS[screen]:
                            window.evaluate_js(THEME_STEPS[screen])
                        for _ in range(6):               # 最多等 3 秒
                            time.sleep(0.5)
                            if window.evaluate_js(THEME_READY[screen]):
                                ready = True
                                break
                        if ready:
                            break
                        window.evaluate_js(THEME_RESET)
                        time.sleep(0.9)
                    if not ready:
                        unready.append(f"{style}-{mode}-{screen}")
                        continue                         # 页不对就不录，别把错位当外观
                    theme_wait_ring_settled(window)
                    shot = THEME_SHOTS / f"{style}-{mode}-{screen}.png"
                    capture(hwnd, shot)
                    for _ in range(2):                   # 画面没跟上明暗（换主题没画完）就重来
                        if theme_capture_sane(shot, mode):
                            break
                        applied = theme_apply(window, style, mode)
                        time.sleep(1.0)
                        capture(hwnd, shot)
                    if not theme_capture_sane(shot, mode):
                        unready.append(f"{style}-{mode}-{screen}（明暗没画完）")
                        continue
                    key = f"{style}-{mode}-{screen}"
                    shots[key] = theme_fingerprint(shot)
                    shots[key]["applied"] = applied
                    if update_baseline or key not in baseline:
                        continue
                    worst, cell = theme_delta(baseline[key], shots[key])
                    row = {"key": key, "max_delta": worst, "cell": cell,
                           "ok": worst <= THEME_TOLERANCE}
                    diff.append(row)
                    if not row["ok"]:
                        failed.append(f"{key} 网格{cell} 偏差 {worst}")
                time.sleep(0.3)

            report["themes"] = {
                "matrix": [list(row) for row in THEME_MATRIX],
                "screens": list(THEME_SCREENS),
                "grid": list(THEME_GRID),
                "tolerance": THEME_TOLERANCE,
                "layout": "ring",
                "shots_dir": str(THEME_SHOTS),
                "baseline": str(THEME_BASELINE),
                "updated": update_baseline,
                "missing": [f"{style}-{mode}-{screen}"
                            for style, mode in THEME_MATRIX for screen in THEME_SCREENS
                            if not update_baseline and f"{style}-{mode}-{screen}" not in baseline],
                "shots": shots,
                "diff": diff,
                "failed": failed,
                "unapplied": unapplied,
                "unready": unready,
                "spread": theme_spread(shots, THEME_SCREENS),
            }
            complete = len(shots) == len(THEME_MATRIX) * len(THEME_SCREENS)
            if ((update_baseline or report["themes"]["missing"])
                    and complete and not unapplied and not unready):
                THEME_BASELINE.parent.mkdir(parents=True, exist_ok=True)
                THEME_BASELINE.write_text(json.dumps({
                    "schema": "aurora.theme-baseline/1",
                    "note": "四套风格 × 深/浅的界面指纹：16×10 网格平均色 + 亮度 / 对比度；"
                            "重录：VISUAL_UPDATE_THEME_BASELINE=1 python tools\\visual.py",
                    "grid": list(THEME_GRID),
                    "tolerance": THEME_TOLERANCE,
                    "shots": {key: {k: v for k, v in row.items() if k != "applied"}
                              for key, row in shots.items()},
                }, ensure_ascii=False, indent=1), encoding="utf-8")
                report["themes"]["baseline_written"] = True
            if unapplied:
                failed.extend(f"{row} 主题没切过去" for row in unapplied)
            if unready:
                failed.extend(f"{row} 页面没切过去" for row in unready)
            spread = report["themes"]["spread"]
            if spread.get("ok") is False:
                failed.append(f"区分度 {spread.get('mean')} < 目标 {spread.get('target')}"
                              f"（深色四套两两平均色差，见 docs/frontend-ux-feedback.md 第 2 条）")
        except Exception as exc:
            import traceback

            report["errors"].append(traceback.format_exc()[-500:])
        finally:
            (OUT / "visual-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print("written visual-report.json")
            try:
                window.destroy()
            except Exception:
                pass

    window.events.loaded += lambda: threading.Thread(target=run, daemon=True).start()
    guard_webview_start(window, label="visual", profile=TEST_DATA / "webview")
    webview.start(gui="edgechromium", private_mode=False, http_port=app_main.free_port(),
                  storage_path=str(TEST_DATA / "webview"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
