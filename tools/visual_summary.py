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


def shot_lum(themes: dict, style: str, mode: str, screen: str):
    """某张主题截图的整体亮度（没截到就给个占位，别让汇总脚本崩）。"""
    row = (themes.get("shots") or {}).get(f"{style}-{mode}-{screen}") or {}
    return row.get("lum", "—")


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

themes = d.get("themes")
if themes:
    cols, rows = themes["grid"]
    print("\n主题矩阵（深色 4 套 + 浅色默认主题 × 5 界面）:")
    print(f"   指纹 {cols}×{rows} 网格平均色，容差 ±{themes['tolerance']}；"
          f"截图 {len(themes['shots'])} 张 → {themes['shots_dir']}")
    print(f"   基线 {themes['baseline']}"
          + ("（本次重录）" if themes.get("baseline_written") else ""))
    if themes.get("missing"):
        print(f"   基线缺 {len(themes['missing'])} 张，已按本次结果补齐："
              + ", ".join(themes["missing"][:6]))
    rows_diff = themes.get("diff") or []
    spread = themes.get("spread") or {}
    if spread.get("mean") is not None:
        # P8.6 起这条会判红（低于目标进 visual.py 的 failed）：汇总里也标出来
        ok = spread.get("ok")
        if ok is None:
            ok = spread["mean"] >= spread.get("target", 20)
        flag = "达标" if ok else "✗ **不达标**（已进 failed）"
        print(f"   区分度（深色四套两两平均色差）{spread['mean']} / 目标 ≥ {spread['target']}"
              f"，{flag}；参照：深/浅两态 {spread.get('light_dark_ref')}")
        for row in spread.get("pairs") or []:
            print(f"      {row['pair']:<24} 平均 {row['mean']:>5}  最大 {row['max']}")
    if themes.get("unapplied"):
        print(f"   ✗ 有 {len(themes['unapplied'])} 套主题没切过去，本次已跳过："
              + ", ".join(themes["unapplied"]))
    if themes.get("unready"):
        print(f"   ✗ 有 {len(themes['unready'])} 张页面没切到位，本次已跳过："
              + ", ".join(themes["unready"][:8]))
    if rows_diff:
        worst = max(rows_diff, key=lambda row: row["max_delta"])
        print(f"   比对 {len(rows_diff)} 张："
              + ("全部在容差内" if not themes["failed"] else f"超限 {len(themes['failed'])} 张")
              + f"（最大偏差 {worst['max_delta']} @ {worst['key']}）")
        for row in rows_diff:
            if not row["ok"]:
                print(f"   ✗ {row['key']} 网格{row['cell']} 偏差 {row['max_delta']}")
        for style, mode in themes["matrix"]:
            line = " ".join(f"{screen}={shot_lum(themes, style, mode, screen)}"
                            for screen in themes["screens"])
            print(f"   {style}-{mode:<5} 亮度 {line}")
    elif not themes.get("updated"):
        print("   还没有基线，本次结果已写入基线文件")

print("\nerrors:", d.get("errors"))
