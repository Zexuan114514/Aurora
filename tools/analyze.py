"""对窗口截图做量化分析（当前模型无法直接看图）。区域用相对坐标表示。

区域坐标按**大厅（默认视图）**标定；要分析游戏页请先用 SNAP_JS 点进游戏再截图。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

SHOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "shot.png"
OUT = Path(__file__).resolve().parent / "analyze-report.txt"
RAMP = " .:-=+*#%@"

# (x0, y0, x1, y1) 以 CSS 视口尺寸为单位，运行时按实际尺寸缩放
REGIONS = [
    ("工具条", (12, 12, 1344, 70)),
    ("背景上缘", (340, 90, 1020, 180)),
    ("左邻封面", (396, 239, 568, 497)),
    ("焦点封面", (578, 208, 778, 507)),
    ("右邻封面", (788, 239, 960, 497)),
    ("底部信息带", (34, 735, 1322, 805)),
    ("左上角", (0, 0, 12, 12)),
    ("右上角", (1344, 0, 1356, 12)),
    ("右下角", (1344, 805, 1356, 817)),
]
DESIGN = (1356, 817)

# 单点采样 (css_x, css_y) -> 标签
POINTS = [
    (700, 40, "工具条玻璃"),
    (700, 130, "焦点上方壁纸"),
    (678, 355, "焦点封面中心"),
    (482, 368, "左邻封面中心"),
    (874, 368, "右邻封面中心"),
    (60, 770, "底部游戏名"),
    (1200, 775, "底部操作提示"),
    (678, 300, "焦点封面中段"),
    (678, 460, "焦点封面下段"),
]

lines: list[str] = []


def p(*a):
    lines.append(" ".join(str(x) for x in a))


def scaled(box, size):
    sx, sy = size[0] / DESIGN[0], size[1] / DESIGN[1]
    return (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))


def region_stat(img, box, label):
    crop = img.crop(box).convert("RGB")
    stat = ImageStat.Stat(crop)
    gray = crop.convert("L")
    gstat = ImageStat.Stat(gray)
    edges = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES))
    p(f"  {label:10} mean=({stat.mean[0]:5.1f},{stat.mean[1]:5.1f},{stat.mean[2]:5.1f}) "
      f"lum={gstat.mean[0]:5.1f} sd={gstat.stddev[0]:5.1f} edge={edges.mean[0]:5.1f}")


def ascii_map(img, cols=120, rows=52):
    small = img.convert("L").resize((cols, rows), Image.LANCZOS)
    px = small.load()
    p("  亮度图:")
    for y in range(rows):
        p("    |" + "".join(RAMP[min(len(RAMP) - 1, px[x, y] * len(RAMP) // 256)]
                            for x in range(cols)) + "|")


def hue_map(img, cols=90, rows=34):
    small = img.convert("RGB").resize((cols, rows), Image.LANCZOS)
    px = small.load()
    p("  色相图 (R红 G绿 B蓝 C青 M品红 Y黄 W灰 K黑 .暗):")
    for y in range(rows):
        line = ""
        for x in range(cols):
            r, g, b = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            if mx < 34:
                line += "K"
            elif mx - mn < 26:
                line += "W" if mx > 150 else ("w" if mx > 70 else ".")
            elif r == mx and g == mn:
                line += "R"
            elif g == mx and b == mn:
                line += "G"
            elif b == mx and r == mn:
                line += "B"
            elif r == mx and b == mn:
                line += "M"
            elif g == mx and r == mn:
                line += "C"
            else:
                line += "Y"
        p("    |" + line + "|")


def text_bands(img, box, label, min_h=5):
    gray = img.crop(box).convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    w, h = edges.size
    px = edges.load()
    rows = [sum(px[x, y] for x in range(w)) / w for y in range(h)]
    # 参考最强的一行来定阈值：文字密的时候也不会因为均值被抬高而漏检
    threshold = max(6.0, (max(rows) if rows else 0) * 0.42)
    bands, start = [], None
    for y, value in enumerate(rows):
        if value >= threshold and start is None:
            start = y
        elif value < threshold and start is not None:
            if y - start >= min_h:
                bands.append((start, y - start))
            start = None
    if start is not None and h - start >= min_h:
        bands.append((start, h - start))
    p(f"  {label:10} 文字行(y,高): " + ", ".join(f"({a},{b})" for a, b in bands[:16]))


def main() -> int:
    img = Image.open(SHOT).convert("RGB")
    size = img.size
    p(f"截图 {size[0]}x{size[1]}  (设计尺寸 {DESIGN[0]}x{DESIGN[1]})")

    p("")
    p("== 区域统计 ==")
    for label, box in REGIONS:
        region_stat(img, scaled(box, size), label)

    p("")
    p("== 单点采样 ==")
    px = img.load()
    sx, sy = size[0] / DESIGN[0], size[1] / DESIGN[1]
    for cx, cy, label in POINTS:
        x, y = int(cx * sx), int(cy * sy)
        if 0 <= x < size[0] and 0 <= y < size[1]:
            r, g, b = px[x, y]
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            p(f"  {label:10} css=({cx},{cy}) rgb=({r:3},{g:3},{b:3}) lum={lum:5.1f}")

    p("")
    p("== 文字行检测（高度应接近字号×1.75）==")
    text_bands(img, scaled((29, 18, 300, 64), size), "工具条左")
    text_bands(img, scaled((34, 730, 300, 778), size), "底部游戏名")
    text_bands(img, scaled((34, 770, 320, 800), size), "底部副标题")
    text_bands(img, scaled((1160, 765, 1330, 800), size), "底部提示")
    text_bands(img, scaled((357, 560, 1000, 640), size), "游戏页标题区")
    text_bands(img, scaled((357, 640, 1000, 720), size), "游戏页简介")

    p("")
    p("== 亮度图 ==")
    ascii_map(img)
    p("")
    p("== 色相图 ==")
    hue_map(img)

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
