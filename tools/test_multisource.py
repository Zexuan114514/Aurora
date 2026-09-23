"""端到端验证多资料源：导入一个 Steam 上搜不到的 galgame，看能否自动匹配。

用到的样例：`サノバウィッチ`（Steam 无此条目，VNDB / Bangumi 有）。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import guard_webview_start, setup_console  # noqa: E402

setup_console()

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox"
TEST_DATA = SANDBOX / "multi-data"
os.environ["AURORA_DATA"] = str(TEST_DATA)

import webview  # noqa: E402

import main as app_main  # noqa: E402
from gl.api import Api  # noqa: E402

OUT = Path(__file__).resolve().parent / "multisource-report.json"
results: list[dict] = []

# (目录名, exe 名, 期望的资料源) —— 第一个是 Steam 上没有的日文 galgame
CASES = [
    ("サノバウィッチ", "サノバウィッチ.exe", "vndb"),
    ("千恋万花", "senrenbanka.exe", "steam"),
]


def step(name: str, ok: bool, detail=""):
    results.append({"step": name, "ok": bool(ok), "detail": detail})
    print(("  PASS " if ok else "  FAIL ") + name + (f"  {detail}" if detail else ""))


def probe(window, js: str):
    raw = window.evaluate_js(f"(() => {{ {js} }})()")
    try:
        return json.loads(raw)
    except Exception:
        return raw


def main() -> int:
    if TEST_DATA.exists():
        shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)
    src = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "ping.exe"

    api = Api()
    window = app_main.build_window(api)
    api._window = window

    def run() -> None:
        time.sleep(6)
        try:
            step("默认启用了 3 个内置源",
                 len([s for s in api._sources.describe() if s["enabled"]]) == 3,
                 [s["id"] for s in api._sources.describe()])

            for folder, exe_name, expect_source in CASES:
                target_dir = SANDBOX / "gal" / folder
                target_dir.mkdir(parents=True, exist_ok=True)
                exe = target_dir / exe_name
                if not exe.exists():
                    shutil.copy2(src, exe)

                res = api.add_by_path(str(exe))
                if not res.get("ok"):
                    step(f"导入 {folder}", False, res)
                    continue
                game_id = res["game"]["id"]

                deadline = time.time() + 120
                game = None
                while time.time() < deadline:
                    time.sleep(2)
                    game = api._library.get(game_id)
                    if game.get("metadata_state") in ("ok", "notfound", "error"):
                        break
                step(f"{folder} 自动匹配", game.get("metadata_state") == "ok",
                     f"source={game.get('data_source')} name={game.get('name')} "
                     f"score={game.get('match_score')}")
                if game.get("metadata_state") != "ok":
                    step(f"{folder} 候选可手动选择", bool(game.get("candidates")),
                         f"{len(game.get('candidates') or [])} 个候选")
                    continue

                step(f"{folder} 匹配到预期的资料源",
                     game.get("data_source") == expect_source,
                     f"期望 {expect_source}，实际 {game.get('data_source')}")
                step(f"{folder} 拿到中文名", bool(game.get("name_cn")), game.get("name_cn"))
                step(f"{folder} 拿到简介", len(game.get("description") or "") > 30,
                     f"{len(game.get('description') or '')} 字")
                step(f"{folder} 拿到图片", len(game.get("images") or []) >= 3,
                     f"{len(game.get('images') or [])} 张")
                step(f"{folder} 默认背景已设置", bool(game.get("background")),
                     (game.get("background") or "")[-40:])

            # 界面：候选面板来源标注 + 资料源面板
            state = probe(window, """
              const rows = document.querySelectorAll('#sourceList .src-row');
              return JSON.stringify({sources: rows.length,
                                     list: document.querySelectorAll('.gi').length,
                                     pills: (document.getElementById('pillSource')||{}).textContent});
            """)
            step("界面显示了资料源列表", (state.get("sources") or 0) >= 3, state)
            step("界面显示游戏数量", (state.get("list") or 0) >= 2, state.get("list"))
            step("信息卡显示资料来源", "·" in (state.get("pills") or ""), state.get("pills"))

            # 关闭 VNDB 后，同一个游戏应该只能靠 Bangumi / Steam
            api.toggle_source("vndb", False)
            api.toggle_source("bangumi", False)
            result = api._sources.resolve(["サノバウィッチ"])
            step("停用非 Steam 源后不再命中 VNDB",
                 not (result.get("ok") and result.get("source") == "vndb"),
                 f"ok={result.get('ok')} source={result.get('source')}")
            api.toggle_source("vndb", True)
            api.toggle_source("bangumi", True)

            # 自定义源
            added = api.add_custom_source({
                "name": "TouchGal", "kind": "link",
                "search_url": "https://www.touchgal.ink/search?query={query}",
            })
            step("添加跳转型自定义源", added.get("ok"),
                 (added.get("source") or {}).get("id"))
            links = api._sources.link_sources()
            step("跳转型源可用于搜索", bool(links), [s["name"] for s in links])
            url = api._sources.get(links[0]["id"]).link_for("千恋万花")
            step("生成搜索链接", "touchgal" in url, url)
            api.remove_custom_source(links[0]["id"])
            step("删除自定义源", not api._sources.link_sources())
        except Exception as exc:  # pragma: no cover
            import traceback
            step("异常", False, traceback.format_exc()[-500:])
        finally:
            OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            passed = sum(1 for r in results if r["ok"])
            print(f"\n{passed}/{len(results)} passed -> {OUT}")
            try:
                window.destroy()
            except Exception:
                pass

    window.events.loaded += lambda: threading.Thread(target=run, daemon=True).start()
    guard_webview_start(window, label="test_multisource", profile=TEST_DATA / "webview")
    webview.start(gui="edgechromium", private_mode=False, http_port=app_main.free_port(),
                  storage_path=str(TEST_DATA / "webview"))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
