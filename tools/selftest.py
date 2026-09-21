"""离线自检：名称推断 + Steam 检索 + 背景图候选。结果写入 UTF-8 报告。"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gl import detect, metadata  # noqa: E402

REPORT = Path(__file__).resolve().parent / "selftest-report.txt"

CASES = [
    r"D:\SteamLibrary\steamapps\common\ELDEN RING\Game\eldenring.exe",
    r"D:\Games\Cyberpunk 2077\bin\x64\Cyberpunk2077.exe",
    r"E:\Games\Black Myth Wukong\b1\Binaries\Win64\b1-Win64-Shipping.exe",
    r"D:\Hades\Hades.exe",
    r"D:\Games\Stardew Valley\Stardew Valley.exe",
    r"D:\Games\Hollow Knight\Hollow Knight.exe",
    r"D:\Games\Baldurs Gate 3\bin\bg3.exe",
    r"E:\Games\It Takes Two\ItTakesTwo.exe",
    r"D:\Games\黑神话悟空\b1\b1.exe",
    r"D:\Games\The Witcher 3 Wild Hunt\bin\x64\witcher3.exe",
]


def main() -> int:
    out = io.StringIO()
    p = lambda *a: print(*a, file=out)  # noqa: E731

    p("=" * 78)
    p("1) 路径 -> 查询名")
    p("=" * 78)
    for case in CASES:
        info = detect.describe_path(Path(case))
        p(f"  {case}")
        p(f"    candidates = {info['candidates']}")
        p(f"    strong     = {info['strong_queries']}")

    p("")
    p("=" * 78)
    p("2) 多源搜索与匹配")
    p("=" * 78)
    ok_count = 0
    for case in CASES:
        info = detect.describe_path(Path(case))
        queries = info["strong_queries"] or info["queries"]
        t0 = time.time()
        result = metadata.resolve(queries)
        dt = time.time() - t0
        if result.get("ok"):
            ok_count += 1
            p(f"  OK   {queries[0]!r} -> {result['source']}:{result['source_id']} "
              f"{result['name']!r} score={result['score']} ({dt:.1f}s)")
        else:
            p(f"  FAIL {queries[0]!r} reason={result.get('reason')} ({dt:.1f}s)")
            for cand in (result.get("candidates") or [])[:5]:
                p(f"         - [{cand['source']}] {cand['name']} ({cand['source_id']}) {cand['score']}")

    p("")
    p("=" * 78)
    p("3) 详情与背景图候选")
    p("=" * 78)
    for case in CASES[:2]:
        info = detect.describe_path(Path(case))
        result = metadata.resolve(info["strong_queries"] or info["queries"])
        if not result.get("ok"):
            continue
        data = metadata.manager().build(result["source"], result["source_id"],
                                        result["name"], lang="schinese") or {}
        p(f"  来源: {result['source']}:{result['source_id']}   {data.get('source_url')}")
        p(f"  名称: {data.get('name')}   (中文名 {data.get('name_cn')} / 原名 {data.get('name_original')})")
        p(f"  开发商: {data.get('developers')}   发行: {data.get('release_date')}   "
          f"类型: {data.get('genres')}")
        p(f"  简介: {(data.get('description') or '')[:110]}...")
        p(f"  封面: {data.get('cover')}")
        p(f"  LOGO: {data.get('logo') or '(无)'}")
        p(f"  背景候选 {len(data.get('images') or [])} 张:")
        for img in (data.get("images") or [])[:8]:
            p(f"    [{img['kind']:10}] {img['label']:16} {img['url']}")
        p("")

    p(f"匹配成功 {ok_count}/{len(CASES)}")
    text = out.getvalue()
    REPORT.write_text(text, encoding="utf-8")
    print(f"report written: {REPORT}  ({ok_count}/{len(CASES)} matched)")
    return 0 if ok_count >= len(CASES) - 1 else 1


if __name__ == "__main__":
    sys.exit(main())
