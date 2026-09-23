"""前端构建新鲜度守卫（v2，纯 Python，CI 不需要 Node）。

`gl/web/v2/` 是 `frontend/` 的构建产物，随源码入库；产物由 Vite 生成，
build-info.json 里记着「源码树哈希」。本检查用**同一套算法**在 Python 侧重算：

    sha256( 逐文件: 相对路径 + "\\n" + 归一化(LF) 内容 + "\\n"，按相对路径排序 )

对不上 = 改了源码没重新构建（`cd frontend && npm run build`）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from common import ROOT, Result, main

FRONTEND = ROOT / "frontend"
OUT_DIR = ROOT / "gl" / "web" / "v2"
INFO = OUT_DIR / "build-info.json"

SOURCE_EXT = {".ts", ".vue", ".css", ".html", ".json", ".mjs"}
SKIP_DIRS = {"node_modules", "dist", ".vite", "__pycache__"}
SKIP_FILES = {"package-lock.json", "build-info.json"}
#: Vite 转译 TS 配置时会在 frontend/ 根留下 `vite.config.ts.timestamp-*.mjs`。
#: 正常它会自己删掉；删不掉时（权限 / 沙箱）会污染指纹 —— 两边都跳过它。
SKIP_NAME = re.compile(r"^vite\.config\..*timestamp-.*\.mjs$")


def source_files() -> list[Path]:
    files: list[Path] = []
    for path in FRONTEND.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.name in SKIP_FILES or SKIP_NAME.match(path.name):
            continue
        if path.suffix not in SOURCE_EXT:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(FRONTEND).as_posix())


def source_hash() -> tuple[str, int]:
    digest = hashlib.sha256()
    files = source_files()
    for path in files:
        rel = path.relative_to(FRONTEND).as_posix()
        body = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\n")
        digest.update(body.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest(), len(files)


def check() -> Result:
    result = Result("前端构建（v2）")
    if not FRONTEND.is_dir():
        result.fail("找不到 frontend/（Vite 工程源码）")
        return result
    if not INFO.is_file():
        result.fail("找不到 gl/web/v2/build-info.json（先跑 cd frontend && npm run build）")
        return result

    info = json.loads(INFO.read_text(encoding="utf-8"))
    digest, count = source_hash()
    if info.get("hash") != digest:
        result.fail(
            "产物与源码不一致：frontend/ 改过但没重新构建"
            f"（记录 {str(info.get('hash'))[:12]} / 实际 {digest[:12]}）；"
            "执行 cd frontend && npm run build"
        )
        return result
    if int(info.get("files") or -1) != count:
        result.fail(f"构建指纹记录 {info.get('files')} 个源文件，实际 {count} 个")
        return result

    for name in ("index.html", "overlay.html", "bundle"):
        if not (OUT_DIR / name).exists():
            result.fail(f"gl/web/v2/{name} 不存在（产物不完整）")
    bundle = OUT_DIR / "bundle"
    js = sorted(p.name for p in bundle.glob("*.js")) if bundle.is_dir() else []
    css = sorted(p.name for p in bundle.glob("*.css")) if bundle.is_dir() else []
    if not js or not css:
        result.fail("gl/web/v2/bundle 下缺少 js / css 产物")
        return result
    if (bundle / "assets").exists():
        result.fail("bundle 下出现了 assets/ 目录：会与用户素材挂载点 /assets/ 冲突")

    total = sum(p.stat().st_size for p in OUT_DIR.rglob("*") if p.is_file())
    result.note(f"源码指纹 {digest[:12]}（{count} 个文件）；产物 {total / 1024:.0f} KB / "
                f"{len(js)} js + {len(css)} css")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
