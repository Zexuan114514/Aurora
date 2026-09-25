"""从项目内的透明 PNG 生成 Aurora 的多尺寸 Windows 应用图标。"""
from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "gl" / "assets" / "aurora-icon.png"
OUT = ROOT / "gl" / "assets" / "aurora.ico"
SIZES = (256, 128, 64, 48, 32, 24, 16)


def main() -> int:
    if not SOURCE.is_file():
        print(f"缺少图标源文件：{SOURCE}")
        return 1

    with Image.open(SOURCE) as image:
        if image.size != (512, 512) or image.mode != "RGBA":
            print("图标源文件必须是 512×512 的透明 PNG")
            return 1
        if image.getpixel((0, 0))[3] != 0:
            print("图标源文件四角必须透明")
            return 1
        image.save(OUT, format="ICO", sizes=[(size, size) for size in SIZES])

    with Image.open(OUT) as icon:
        actual = {size[0] for size in icon.ico.sizes()}
    if actual != set(SIZES):
        print(f"图标尺寸不完整：{sorted(actual)}")
        return 1
    print(f"written {OUT} ({OUT.stat().st_size} bytes, {len(SIZES)} 个尺寸)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
