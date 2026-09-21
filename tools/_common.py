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
import pathlib
import sys

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
