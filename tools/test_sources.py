"""资料源自检：逐个源搜索 + 拉详情，检查字段完整性。"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gl.sources import SourceManager  # noqa: E402
from gl.store import Library  # noqa: E402

OUT = Path(__file__).resolve().parent / "sources-report.txt"
QUERIES = ["千恋万花", "サノバウィッチ", "星光咖啡馆与死神之蝶", "NUKITASHI"]
lines: list[str] = []


def p(*a):
    lines.append(" ".join(str(x) for x in a))


manager = SourceManager(Library())

p("=" * 74)
p("已启用的资料源")
p("=" * 74)
for row in manager.describe():
    p(f"  {row['id']:16} {row['name']:16} kind={row['kind']:5} "
      f"{'启用' if row['enabled'] else '停用'}  {row['status']}")

for query in QUERIES:
    p("")
    p("=" * 74)
    p(f"查询：{query}")
    p("=" * 74)
    for source in manager.sources():
        if source.kind != "api":
            continue
        try:
            found = source.search([query], 8.0) or []
        except Exception as exc:
            p(f"  [{source.id}] 搜索异常: {exc}")
            continue
        p(f"  [{source.id}] {len(found)} 个候选")
        for candidate in found[:3]:
            p(f"      {candidate.source_id:10} {candidate.name}   别名={candidate.names[1:3]}")
        if not found:
            continue
        meta = manager.fetch_metadata(source.id, found[0].source_id, found[0].name)
        if meta is None:
            p(f"      -> 拉详情失败")
            continue
        p(f"      -> name={meta.name!r} name_cn={meta.name_cn!r} "
          f"original={meta.name_original!r}")
        p(f"         简介 {len(meta.description)} 字 / 长文 {len(meta.about)} 字 / "
          f"开发商={meta.developers} / 发售={meta.release_date} / 评分={meta.rating}")
        p(f"         封面={'有' if meta.cover else '无'} 图片 {len(meta.images)} 张 "
          f"标签={meta.genres[:4]}")

    result = manager.resolve([query], threshold=0.75, budget=40)
    if result.get("ok"):
        p(f"  >>> 综合最佳：{result['source']} / {result['source_id']} "
          f"{result['name']!r} score={result['score']}")
        data = manager.build(result["source"], result["source_id"], result["name"])
        if data:
            p(f"      入库字段：name={data['name']!r} 简介={len(data['description'])}字 "
              f"图片={len(data['images'])}张 封面源={len(data['cover_sources'])}")
    else:
        p(f"  >>> 未匹配：{result.get('reason')}")
        for candidate in (result.get("candidates") or [])[:5]:
            p(f"      {candidate['source']:8} {candidate['name']} ({candidate['score']})")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
