"""汇总 visual.py 的结果。"""
from __future__ import annotations

import json
from pathlib import Path

d = json.loads((Path(__file__).resolve().parent / "visual-report.json").read_text(encoding="utf-8"))
covers = json.loads(d.get("cover_dom") or "[]")
thumbs = json.loads(d.get("thumb_src") or "[]")

print(f"封面 {len(covers)} 个，全部加载成功: {all(c['natural'] > 0 for c in covers)}")
for c in covers[:3]:
    print(f"   natural={c['natural']:>5} broken={c['broken']}  ...{c['src'][-34:]}")

print("缩略图:")
for t in thumbs:
    print(f"   natural={t['natural']:>5}  broken={t['broken']}  ...{t['src'][-40:]}")

print("封面像素 sd:", [round(c["sd"], 1) for c in d.get("covers", [])])
print("缩略图像素 sd:", [round(t["sd"], 1) for t in d.get("thumbs", [])])

zoom = d.get("zoom") or {}
if zoom:
    print("\n背景缩放/平移:")
    for key in ("before", "after_slider", "after_reset"):
        if key in zoom:
            print(f"   {key:14} {zoom[key]}")

icon = d.get("custom_icon")
if icon:
    dom = json.loads(icon["dom"]) if isinstance(icon.get("dom"), str) else icon.get("dom")
    print("\n自定义图标:")
    print(f"   设置成功     {icon['set_ok']}")
    print(f"   已写入库     {icon['stored']}")
    print(f"   大厅封面渲染 natural={dom.get('natural')}px  src=...{str(dom.get('src'))[-34:]}")
    print(f"   清除后       {icon['after_clear']!r}")

print("\nerrors:", d.get("errors"))
