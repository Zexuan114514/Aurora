"""生成 Aurora 应用图标。

设计：极光渐变圆角方块 + 玻璃高光 + 圆角播放三角。
渲染时超采样再缩放，保证小尺寸下边缘干净。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "gl" / "assets" / "aurora.ico"
PREVIEW = Path(__file__).resolve().parent / "icon-preview.png"

BASE = 512  # 基础渲染尺寸（再放大到超采样用）

# 极光配色（青 -> 蓝 -> 靛 -> 紫）
STOPS = [
    (0.00, (90, 214, 255)),
    (0.34, (34, 148, 255)),
    (0.66, (96, 92, 236)),
    (1.00, (176, 92, 244)),
]


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _gradient(size: int) -> Image.Image:
    """对角渐变（按行/列分段加速，避免逐像素插值过慢）。"""
    img = Image.new("RGB", (size, size))
    px = img.load()
    stops = STOPS
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            for i in range(len(stops) - 1):
                t0, c0 = stops[i]
                t1, c1 = stops[i + 1]
                if t <= t1 or i == len(stops) - 2:
                    local = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                    px[x, y] = _lerp(c0, c1, max(0.0, min(1.0, local)))
                    break
    return img


def _squircle_mask(size: int, radius_ratio: float = 0.235) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=255)
    return mask


def _rounded_polygon(points, size: int, blur: float) -> Image.Image:
    """先画多边形再模糊 + 阈值，得到圆角三角形。"""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    return mask.point(lambda v: 255 if v >= 128 else 0)


def render(size: int) -> Image.Image:
    s = size
    img = _gradient(s).convert("RGBA")
    mask = _squircle_mask(s)

    # 顶部玻璃高光
    gloss = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse([-s * 0.35, -s * 0.80, s * 1.35, s * 0.50],
                                  fill=(255, 255, 255, 64))
    gloss = gloss.filter(ImageFilter.GaussianBlur(s * 0.055))
    img.alpha_composite(Image.composite(gloss, Image.new("RGBA", (s, s), (0, 0, 0, 0)), mask))

    # 底部暗角，让白色三角更突出
    shade = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse([-s * 0.25, s * 0.55, s * 1.25, s * 1.45],
                                  fill=(6, 10, 40, 96))
    shade = shade.filter(ImageFilter.GaussianBlur(s * 0.07))
    img.alpha_composite(Image.composite(shade, Image.new("RGBA", (s, s), (0, 0, 0, 0)), mask))

    # 圆角播放三角（视觉居中略右移）
    cx, cy = s * 0.535, s * 0.5
    half_h = s * 0.30
    width = s * 0.245
    tri = [(cx - width * 0.62, cy - half_h), (cx + width * 0.78, cy),
           (cx - width * 0.62, cy + half_h)]
    tri_mask = _rounded_polygon(tri, s, s * 0.030)

    # 三角投影
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    shadow.paste((8, 20, 60, 132), (0, int(s * 0.014)), tri_mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(s * 0.022))
    img.alpha_composite(shadow)

    # 三角本体：竖直白 -> 淡蓝渐变
    body = Image.new("RGBA", (s, s), (255, 255, 255, 255))
    bp = body.load()
    for y in range(s):
        color = _lerp((255, 255, 255), (214, 236, 255), y / (s - 1))
        for x in range(s):
            bp[x, y] = color + (255,)
    img.alpha_composite(Image.composite(body, Image.new("RGBA", (s, s), (0, 0, 0, 0)), tri_mask))

    # 玻璃内描边
    edge = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        [s * 0.012, s * 0.012, s * 0.988, s * 0.988],
        radius=int(s * 0.225), outline=(255, 255, 255, 72),
        width=max(1, int(s * 0.008)))
    img.alpha_composite(edge)

    # 套回圆角
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    big = render(BASE * 2)  # 1024，供大尺寸缩放
    sizes = [256, 128, 64, 48, 32, 24, 16]
    frames = [big.resize((n, n), Image.LANCZOS) for n in sizes]
    frames[0].save(OUT, format="ICO", sizes=[(n, n) for n in sizes])
    frames[0].save(PREVIEW)

    px = frames[0].load()
    print(f"written {OUT}  ({OUT.stat().st_size} bytes, {len(sizes)} 个尺寸)")
    print(f"  角落 alpha = {px[2, 2][3]}  (应为 0)")
    print(f"  中心色     = {px[128, 128][:3]}")
    print(f"  预览       = {PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
