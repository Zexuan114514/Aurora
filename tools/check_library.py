"""检查现有游戏库是否完好：结构、重复 id、缺 exe、设置文件。

P2 之后库在 `<数据目录>/state/library.json`（v1 时代是 `data/library.json`）。
旧版本把路径写死成 v1，实测在新布局下直接 FileNotFoundError —— 现在路径统一问
`tools/_common.layout()`，数据布局再变探针也跟着走。

没有数据目录时（CI / 干净 checkout）打印一行「跳过」并以 0 退出，
这样它可以直接被 `tools/checks/check_tools_manifest.py` 拉起来跑。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console, layout  # noqa: E402

setup_console()

import json
from pathlib import Path


def main() -> int:
    paths = layout()
    library_path: Path = paths.library_file
    if not library_path.is_file():
        legacy = paths.legacy_library
        if legacy.is_file():
            print(f"没有 v2 库 {library_path}")
            print(f"但存在 v1 遗留库 {legacy} —— 启动器下次启动会自动迁移（先备份再拆账）")
        else:
            print(f"没有数据目录（{paths.root}），跳过")
        return 0

    data = json.loads(library_path.read_text(encoding="utf-8"))
    games = data.get("games") or []
    print(f"库文件: {library_path}")
    print("游戏数:", len(games))

    problems: list[str] = []
    seen: dict[str, int] = {}
    missing_exe: list[str] = []
    for game in games:
        gid = str(game.get("id") or "")
        name = str(game.get("name") or "")
        exe = str(game.get("exe") or "")
        if not gid:
            problems.append(f"缺 id：{name or '(无名)'}")
        else:
            seen[gid] = seen.get(gid, 0) + 1
        if not name:
            problems.append(f"缺 name：{gid}")
        if not exe:
            problems.append(f"缺 exe：{name or gid}")
        elif not Path(exe).is_file():
            missing_exe.append(f"{name or gid} -> {exe}")
        src = game.get("data_source") or ("steam" if game.get("appid") else "-")
        sid = game.get("source_id") or game.get("appid") or "-"
        print(f"  {name}   [{src}:{sid}]  图片 {len(game.get('images') or [])} 张")

    duplicates = sorted(gid for gid, count in seen.items() if count > 1)
    if duplicates:
        problems.append(f"重复 id：{', '.join(duplicates)}")
    if missing_exe:
        print()
        print(f"exe 已不在原路径（{len(missing_exe)} 个，游戏可能已卸载/移动）：")
        for row in missing_exe:
            print("  ", row)

    settings_path = paths.settings_file
    print()
    print(f"设置文件: {settings_path if settings_path.is_file() else '（缺失）'}")

    if problems:
        print()
        print("库有问题：")
        for row in problems:
            print("  -", row)
        return 1
    print()
    print("结构完好：id / name / exe 齐全，无重复 id")
    return 0


if __name__ == "__main__":
    _sys.exit(main())
