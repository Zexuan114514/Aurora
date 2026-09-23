"""主题自检：4 套配色 × 3 档模式，实测令牌、强调色与深浅色对比度。

结果写入 tools/theme-report.txt。判据（全部来自 getComputedStyle）：
  深色：面板底是「白色低透明度」（r=g=b=255，alpha ≤ 0.4），文字是亮的；
  浅色：面板底是「白色高透明度」（alpha ≥ 0.5），文字是暗的。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import guard_webview_start, setup_console  # noqa: E402

setup_console()

import io
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox" / "theme-probe"
DATA = SANDBOX / "data"
GAMES = SANDBOX / "games"
REPORT = Path(__file__).resolve().parent / "theme-report.txt"
PALETTES = {"aurora": "#0A84FF", "lime": "#26C6A8", "sakura": "#FF5C8A", "amber": "#FF9F0A"}

os.environ["AURORA_DATA"] = str(DATA)

import webview  # noqa: E402

import main as app_main  # noqa: E402
from gl.api import Api  # noqa: E402

failed = 0


def probe(window, js):
    raw = window.evaluate_js(f"(() => {{ {js} }})()")
    try:
        return json.loads(raw)
    except Exception:
        return raw


def prepare() -> None:
    shutil.rmtree(SANDBOX, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)
    GAMES.mkdir(parents=True, exist_ok=True)
    ping = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "ping.exe"
    games = []
    for i in range(3):
        exe = GAMES / f"theme{i}.exe"
        shutil.copy2(ping, exe)
        games.append({"id": f"t{i}", "name": f"主题测试 {i}", "exe": str(exe),
                      "exe_name": exe.name, "dir": str(GAMES), "workdir": str(GAMES),
                      "metadata_state": "ok", "developers": ["测试社"],
                      "cover_sources": [], "images": [], "description": "主题自检"})
    (DATA / "library.json").write_text(json.dumps(
        {"version": 1, "games": games, "bookshelves": [], "settings": {}}, ensure_ascii=False),
        encoding="utf-8")


READ_JS = """
  const panel = document.querySelector('.set-panes') || document.getElementById('toolbar');
  const title = document.getElementById('gTitle') || document.body;
  const parse = (value) => {
    const m = value.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return {r: 0, g: 0, b: 0, a: 1};
    const parts = m[1].split(',').map(Number);
    return {r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1};
  };
  return JSON.stringify({
    theme: document.documentElement.dataset.theme,
    palette: document.documentElement.dataset.palette,
    accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    bg: parse(getComputedStyle(panel).backgroundColor),
    fg: parse(getComputedStyle(title).color)});
"""


def main() -> int:
    global failed
    out = io.StringIO()

    def write(line: str = "") -> None:
        out.write(line + "\n")

    def check(label: str, ok: bool, detail="") -> bool:
        global failed
        if not ok:
            failed += 1
        write(f"  {'OK ' if ok else 'BAD'} {label}" + (f"  {detail}" if detail else ""))
        return ok

    prepare()
    write("Aurora 主题自检")
    write("=" * 52)

    api = Api()
    window = app_main.build_window(api)
    api._window = window

    def run() -> None:
        global failed
        time.sleep(6)
        try:
            for mode in ("dark", "light", "auto"):
                for palette, accent in PALETTES.items():
                    # 必须包在 IIFE 里：evaluate_js 共用页面全局作用域，
                    # 直接写 const 会在第二轮开始重复声明而卡住
                    window.evaluate_js("""
                      (() => {
                        const sel = document.getElementById('setTheme');
                        sel.value = '%s';
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        const chip = document.querySelector('[data-palette="%s"]');
                        if (chip) chip.click();
                        return 1;
                      })();
                    """ % (mode, palette))
                    time.sleep(1.0)
                    info = probe(window, READ_JS)
                    print(f"  {mode}/{palette} -> {info.get('theme')}", flush=True)
                    write(f"\n[mode={mode} palette={palette}] 实际={info.get('theme')}"
                          f" 强调色={info.get('accent')} 面板={info.get('bg')}"
                          f" 文字={info.get('fg')}")
                    theme = info.get("theme")
                    if mode == "auto":
                        check("auto 落到 dark / light", theme in ("dark", "light"), theme)
                    else:
                        check(f"{mode} 模式生效", theme == mode, theme)
                    check("配色预设生效", info.get("palette") == palette, info.get("palette"))
                    check("强调色与预设一致",
                          str(info.get("accent", "")).lower() == accent.lower(),
                          str(info.get("accent")))
                    bg, fg = info.get("bg") or {}, info.get("fg") or {}
                    if theme == "light":
                        check("浅色：面板是白色高透明度",
                              bg.get("a", 0) >= 0.5 and bg.get("r") == 255, str(bg))
                        check("浅色：文字是深色",
                              sum(fg.get(k, 255) for k in "rgb") / 3 < 120, str(fg))
                    else:
                        check("深色：面板是白色低透明度",
                              bg.get("a", 1) <= 0.4 and bg.get("r") == 255, str(bg))
                        check("深色：文字是亮色",
                              sum(fg.get(k, 0) for k in "rgb") / 3 > 140, str(fg))
        except Exception:
            import traceback

            failed += 1
            write("  诊断异常：" + traceback.format_exc()[-300:])
        finally:
            write("\n结论: " + ("全部通过" if not failed else f"{failed} 项失败"))
            text = out.getvalue()
            REPORT.write_text(text, encoding="utf-8")
            print(text, flush=True)
            try:
                window.destroy()
            except Exception:
                pass

    window.events.loaded += lambda: threading.Thread(target=run, daemon=True).start()
    guard_webview_start(window, label="theme_probe", profile=SANDBOX / "webview")
    webview.start(gui="edgechromium", private_mode=False, http_port=app_main.free_port(),
                  storage_path=str(SANDBOX / "webview"))
    api._downloads.stop()
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
