"""用本地缓存验证 build_metadata（不依赖当前网络）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gl import metadata  # noqa: E402

OUT = Path(__file__).resolve().parent / "meta-offline-report.txt"
lines: list[str] = []

data = metadata.build_metadata(1245620, lang="schinese")
lines.append(f"name        = {data['steam_name']}")
lines.append(f"description = {(data['description'] or '')[:60]}...")
lines.append(f"cover       = {data['cover']}")
lines.append(f"cover_chain = {len(data['cover_sources'])} 项")
for i, url in enumerate(data["cover_sources"][:6], 1):
    lines.append(f"   {i}. {url}")
lines.append(f"logo        = {data['logo']}")
lines.append(f"images      = {len(data['images'])} 张")
for img in data["images"][:5]:
    lines.append(f"   [{img['kind']:10}] {img['label']:16} thumb={img['thumb'][-40:]}")
lines.append(f"developers  = {data['developers']}  genres={data['genres']}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
