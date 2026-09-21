"""汇总 visual.py 的结果。"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

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

ring = d.get("ring") or {}
check = d.get("ring_check") or {}
if check:
    print("\n大厅环形队列（封面 / 倾斜角 / 高度）:")
    for key, deg, h in check.get("visible", []):
        print(f"   {key:<8} rotateY={deg:>6}° 高={h:>6}")
    ok = (check.get("sizes_shrink_outwards") and check.get("all_tilted")
          and check.get("front_is_biggest") and abs(check.get("focus_center_delta", 99)) <= 3)
    print(f"   越远越小={check.get('sizes_shrink_outwards')} "
          f"都有倾斜={check.get('all_tilted')} "
          f"焦点最大={check.get('front_is_biggest')} "
          f"焦点居中偏差={check.get('focus_center_delta')}px -> {'通过' if ok else '不通过'}")
    keys = (ring.get("ring") or {}).get("keys") or []
    print(f"   环上顺序（前 6 个）: {[k[:6] for k in keys[:6]]}")

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
