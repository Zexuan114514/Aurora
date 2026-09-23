"""一次性迁移：把 v1 的 gl/web/app.css 变成 v2 的 src/styles/layout.css。

做三件事：
  1. 剥掉定义变量值的 `:root { … }` 与 `[data-theme="light"] { … }` 两个块
     —— 值现在由 src/styles/tokens.css + themes/*.tokens.css 提供。
  2. 去掉四条调色板块（--accent 由主题给）。
  3. 其余规则原样保留（布局与环形几何是 e2e / visual 的判据，不动）。

跑完即删，产出物随源码入库。
"""
from pathlib import Path

SRC = Path(r"C:\Users\HuHu1\Desktop\Tasks\v4.1\Aurora\gl\web\app.css")
OUT = Path(r"C:\Users\HuHu1\Desktop\Tasks\v4.1\Aurora\frontend\src\styles\layout.css")

HEADER = """/* Aurora v2 · 布局层
 *
 * 这一层从 v1 的 gl/web/app.css 机械迁移而来（见 frontend/scripts 的迁移说明）：
 * 所有规则原样保留，只把「定义变量值」的几个块剥掉了 —— 颜色 / 圆角 / 模糊 /
 * 强调色现在由 src/styles/tokens.css 与 themes/*.tokens.css 提供。
 *
 * 为什么保留而不是重写：环形封面流的几何（left/top 50%、perspective、transform
 * 由 JS 每帧写）是 tools/visual.py 与 tools/e2e.py 的判据，重写等于重做整套回归网。
 * 视觉风格靠主题层切换，布局只有一套。
 */

"""


def block_range(lines: list[str], opener: str) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        if line.strip().startswith(opener):
            depth = 0
            for end in range(index, len(lines)):
                depth += lines[end].count("{") - lines[end].count("}")
                if depth == 0 and end > index:
                    return index, end
            return index, len(lines) - 1
    return None


def main() -> int:
    lines = SRC.read_text(encoding="utf-8").split("\n")
    root = block_range(lines, ":root {")
    light = block_range(lines, '[data-theme="light"] {')
    if not root or not light:
        raise SystemExit(f"找不到变量块：root={root} light={light}")

    kept: list[str] = []
    for index, line in enumerate(lines):
        if root[0] <= index <= root[1]:
            continue
        if light[0] <= index <= light[1]:
            continue
        if line.strip().startswith("[data-palette="):
            continue
        kept.append(line)

    body = "\n".join(kept)
    body = body.replace('[data-theme="light"]', '[data-mode="light"]')
    OUT.write_text(HEADER + body.lstrip("\n"), encoding="utf-8", newline="\n")
    print(f"layout.css: {len(lines)} → {len(kept)} 行")
    print(f"剥离 :root 第 {root[0]+1}–{root[1]+1} 行；浅色块第 {light[0]+1}–{light[1]+1} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
