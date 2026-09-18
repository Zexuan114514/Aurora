"""视觉自检：大厅封面 + 背景选择面板缩略图是否真的渲染出来了。"""
from __future__ import annotations

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


def capture(hwnd: int, path: Path) -> tuple[int, int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
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
    return w, h


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
    webview.start(gui="edgechromium", private_mode=False, http_port=app_main.free_port(),
                  storage_path=str(TEST_DATA / "webview"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
