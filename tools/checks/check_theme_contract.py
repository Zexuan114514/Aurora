"""主题契约守卫（v2）：

1. tokens.css 里 `@contract` 标记的 :root 是**令牌清单**的唯一来源；
2. 每套主题（aurora / gallery / screening / shelf）都必须在深色块与
   `[data-mode="light"]` 块里补齐全部令牌 —— 少一个就红；
3. tokens 文件只允许声明自定义属性；
4. 每个 skin 文件 ≤200 行，且每条选择器都要以 `[data-style="…"]` 开头。
   一套主题可以有多张皮肤（P8.16 起：主题签名 `<theme>.skin.css` + 按钮语言
   `<theme>.buttons.skin.css`），**逐张**受这条约束 —— 别把新 sheet 放在
   守卫扫不到的名字下。
   （风格可以加结构钩子与自己的覆盖，但不许改布局的通用规则）。
   P8.4 起放宽到 200 行：主题签名不再只是颜色 —— 排印、分隔线、封面呈现、
  背景处理都要能改（见 docs/frontend-ux-feedback.md 第 2 条与 p8 交付记录的 P8.4 小节）。
  允许皮肤挂 `[data-slot="…"]` 这类结构性钩子；几何与 92 个探针 id 仍是冻结面。
4.5 **圆角只能走令牌**（P8.7）：共享布局层（layout.css / app.css / element.css）里
   不许再出现写死的 `border-radius` 数值 —— 否则「画廊 / 放映厅 是方角，
   极光玻璃是圆角」这条设计语言在某个组件上会破功。窗口外形（body / #app 的 10px）
   与正圆（50%）例外。
5. 主题截图基线（tools/baselines/theme-baseline.json）形状完整：
   5 套配置 × 5 个界面 = 25 条指纹，网格大小与容差齐全，深浅两态不能一模一样。
6. **令牌值域**（P8.8）：契约只管「补齐了没」，这一节管「补的值合不合理」——
   `--s-floor` 的不透明度 60–95%、`--fx-blur` 非负且只有极光玻璃保留毛玻璃、
   `--r-*` 档位单调不减、饱和度 / 压暗 / 阶梯倍率在合理区间。
   起因见 docs/frontend-ux-feedback.md 第 3 / 11 条：`--s-floor` 一丢，深色态面板就退回
   「96% 壁纸 + 4% 白」，文字对比度掉到 1.04，而 e2e / visual 全绿 —— 看不见。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from common import ROOT, Result, main

STYLES = ROOT / "frontend" / "src" / "styles"
THEMES = ("aurora", "gallery", "screening", "shelf")
TOKENS = STYLES / "tokens.css"
SKIN_MAX_LINES = 200

#: 主题截图基线（tools/visual.py 生成，见 docs/architecture/p8-frontend-v2.md）
BASELINE = ROOT / "tools" / "baselines" / "theme-baseline.json"
BASELINE_MATRIX = (("aurora", "dark"), ("gallery", "dark"), ("screening", "dark"),
                   ("shelf", "dark"), ("aurora", "light"))
BASELINE_SCREENS = ("hall", "game", "categories", "settings", "panel")

_CONTRACT = re.compile(r"/\* @contract:start \*/(.*?)/\* @contract:end \*/", re.S)
_DECL = re.compile(r"(--[a-z0-9-]+)\s*:", re.I)
_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)

#: 圆角守卫：这三个文件是「一套布局」的共享层，圆角必须来自 --r-* 令牌
RADIUS_FILES = ("layout.css", "app.css", "element.css")
_RADIUS_DECL = re.compile(r"border-radius\s*:\s*([^;]+);", re.I)
_RADIUS_TOKEN = re.compile(r"^(50%|inherit|0|var\(--r-[a-z-]+\)|calc\(var\(--r-)", re.I)
#: 窗口自己的外形（无边框窗口的 10px 圆角）不属于组件语言
_WINDOW_SELECTOR = re.compile(r"^\s*(body|#app)\s*(\{|,|$)", re.I)

#: 带值的声明（值域检查要读具体数值，不能只看名字）
_DECL_VALUE = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", re.I)
_PCT_VALUE = re.compile(r"(\d+(?:\.\d+)?)%")

#: 圆角的「档位次序」：小 → 大必须单调不减。
#: 胶囊（--r-pill）单独一档 —— 方角主题里它也很小，不参与这条链。
_RADIUS_LADDER = ("--r-xs", "--r-sm", "--r-md", "--r-lg", "--r-xl")

#: 模糊口径（P8.8 拍板）：四套里**只有极光玻璃**保留毛玻璃，其余一律 0。
#: 极光给下限 12px —— 那是这套主题的身份，别又抹成 0（反馈第 11 条）。
BLUR_BY_THEME = {"aurora": (12, 40), "gallery": (0, 0), "screening": (0, 0), "shelf": (0, 0)}

#: 其余区间量：(令牌, 下限, 上限, 说明)
VALUE_RANGES = (
    ("--fx-sat", 0, 400, "表面饱和度倍率"),
    ("--fx-scrim", 0, 1, "壁纸压暗强度"),
    ("--scrim-boost", 0, 5, "压暗倍率"),
    ("--ramp-s-k", 0, 20, "表面阶梯倍率"),
    ("--ramp-l-k", 0, 20, "描边阶梯倍率"),
)


def radius_issues() -> list[str]:
    """共享层里有没有写死的圆角（除了窗口外形与正圆）。"""
    issues: list[str] = []
    for name in RADIUS_FILES:
        path = STYLES / name
        if not path.is_file():
            continue
        selector = ""
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "{" in line and not line.strip().startswith(("/*", "*", "@")):
                selector = line.split("{")[0].strip()
            matched = _RADIUS_DECL.search(line)
            if not matched:
                continue
            value = matched.group(1).strip()
            if _RADIUS_TOKEN.match(value) or _WINDOW_SELECTOR.match(selector):
                continue
            issues.append(f"{name}:{lineno} 的圆角写死了（{value}）——改用 --r-xs/sm/md/lg/xl/pill")
    return issues


def contract_tokens() -> list[str]:
    text = TOKENS.read_text(encoding="utf-8")
    matched = _CONTRACT.search(text)
    if not matched:
        raise SystemExit("tokens.css 里找不到 @contract 标记块")
    seen: list[str] = []
    for name in _DECL.findall(matched.group(1)):
        if name not in seen:
            seen.append(name)
    return seen


def theme_block(text: str, theme: str, light: bool) -> set[str] | None:
    for selector, body in _BLOCK.findall(text):
        sel = selector.strip()
        if f'[data-style="{theme}"]' not in sel:
            continue
        is_light = '[data-theme="light"]' in sel
        if is_light == light:
            return set(_DECL.findall(body))
    return None


def baseline_issues() -> list[str]:
    """主题截图基线的形状检查（内容是 tools/visual.py 跑出来的）。"""
    if not BASELINE.is_file():
        return ["缺少主题截图基线 tools/baselines/theme-baseline.json"
                "（重录：$env:VISUAL_UPDATE_THEME_BASELINE=1; python tools\\visual.py）"]
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"主题截图基线读不出来：{type(exc).__name__}: {exc}"]

    issues: list[str] = []
    if data.get("schema") != "aurora.theme-baseline/1":
        issues.append(f"主题截图基线 schema 不对：{data.get('schema')!r}")
    grid = data.get("grid") or []
    if len(grid) != 2 or not all(isinstance(n, int) and n > 0 for n in grid):
        issues.append(f"主题截图基线 grid 不对：{grid!r}")
        return issues
    cells_expected = grid[0] * grid[1]

    shots = data.get("shots") or {}
    expected = {f"{style}-{mode}-{screen}"
                for style, mode in BASELINE_MATRIX for screen in BASELINE_SCREENS}
    for key in sorted(expected - set(shots)):
        issues.append(f"主题截图基线缺 {key}")
    for key in sorted(set(shots) - expected):
        issues.append(f"主题截图基线多了 {key}（矩阵只有 4 套深色 + 浅色默认主题）")
    for key, row in sorted(shots.items()):
        cells = row.get("cells") or []
        if len(cells) != cells_expected:
            issues.append(f"{key} 的网格是 {len(cells)} 格，应为 {cells_expected}")
        elif any(len(cell) != 3 for cell in cells):
            issues.append(f"{key} 有不是 RGB 三通道的格子")
        if not isinstance(row.get("lum"), (int, float)):
            issues.append(f"{key} 缺 lum（整体亮度）")
        if not isinstance(row.get("sd"), (int, float)):
            issues.append(f"{key} 缺 sd（对比度）")

    # 深 / 浅两态必须真的不一样：一样就说明基线是同一张图抄出来的
    for style, mode in BASELINE_MATRIX:
        if mode != "dark":
            continue
        other = f"{style}-light-{BASELINE_SCREENS[0]}"
        dark = shots.get(f"{style}-dark-{BASELINE_SCREENS[0]}") or {}
        if dark.get("cells") and dark.get("cells") == (shots.get(other) or {}).get("cells"):
            issues.append(f"{style} 的深色与浅色指纹一模一样（基线录歪了）")
    return issues


def _px(value: str) -> float | None:
    """`20px` → 20；不是 px 值返回 None。"""
    text = value.strip()
    if not text.endswith("px"):
        return None
    try:
        return float(text[:-2])
    except ValueError:
        return None


def _number(value: str) -> float | None:
    """`190%` / `0.42` → 数；解析不出返回 None。"""
    try:
        return float(value.strip().rstrip("%"))
    except ValueError:
        return None


def theme_values(text: str, theme: str, light: bool) -> dict[str, str]:
    """主题块里的 令牌 → 值（同名取最后一次，跟 CSS 的层叠一致）。"""
    for selector, body in _BLOCK.findall(text):
        sel = selector.strip()
        if f'[data-style="{theme}"]' not in sel:
            continue
        if ('[data-theme="light"]' in sel) != light:
            continue
        return {name.lower(): value.strip() for name, value in _DECL_VALUE.findall(body)}
    return {}


def value_issues() -> list[str]:
    """令牌值域：写「能看」的守卫（见模块 docstring 第 6 条）。"""
    issues: list[str] = []
    for theme in THEMES:
        path = STYLES / "themes" / f"{theme}.tokens.css"
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for light, label in ((False, "深色"), (True, "浅色")):
            values = theme_values(text, theme, light)
            if not values:
                continue
            where = f"{theme} · {label}"

            # --s-floor：面板底衬的不透明度必须落在 60–95%
            floor = values.get("--s-floor", "")
            pct = _PCT_VALUE.search(floor)
            if "color-mix" not in floor or not pct:
                issues.append(f"{where} 的 --s-floor 不是 color-mix(… N%, transparent)"
                              f"（{floor or '缺'}）")
            else:
                percent = float(pct.group(1))
                if not 60 <= percent <= 95:
                    issues.append(f"{where} 的 --s-floor 不透明度是 {percent:g}%，应在 60–95%"
                                  "（丢了它深色态就退回「亮底白字」，见反馈第 3 条）")

            # --fx-blur：非负；且只有极光玻璃保留毛玻璃
            blur = _px(values.get("--fx-blur", ""))
            if blur is None:
                issues.append(f"{where} 的 --fx-blur 不是 px 值（{values.get('--fx-blur', '缺')}）")
            elif blur < 0:
                issues.append(f"{where} 的 --fx-blur 是负数（{blur:g}px）")
            else:
                low, high = BLUR_BY_THEME.get(theme, (0, 400))
                if not low <= blur <= high:
                    if low == high == 0:
                        issues.append(f"{where} 的 --fx-blur 是 {blur:g}px，这一套不该有模糊"
                                      "（四套里只有极光玻璃保留毛玻璃）")
                    else:
                        issues.append(f"{where} 的 --fx-blur 是 {blur:g}px，应在 {low}–{high}px"
                                      "（毛玻璃是极光玻璃的身份，别抹成 0）")

            # 其余区间量
            for name, low, high, note in VALUE_RANGES:
                raw = values.get(name)
                if raw is None:
                    continue
                number = _number(raw)
                if number is None:
                    issues.append(f"{where} 的 {name} 不是数值（{raw}）")
                elif not low <= number <= high:
                    issues.append(f"{where} 的 {name}（{note}）是 {number:g}，应在 {low}–{high}")

            # --r-* 单调不减（小 → 大）
            ladder: list[tuple[str, float]] = []
            for name in _RADIUS_LADDER:
                number = _px(values.get(name, ""))
                if number is None:
                    issues.append(f"{where} 的 {name} 不是 px 值（{values.get(name, '缺')}）")
                    ladder = []
                    break
                ladder.append((name, number))
            for (prev_name, prev), (name, value) in zip(ladder, ladder[1:]):
                if value < prev:
                    issues.append(f"{where} 的圆角档位反了：{name} {value:g}px < "
                                  f"{prev_name} {prev:g}px（小 → 大必须单调不减）")
            pill = _px(values.get("--r-pill", ""))
            if pill is not None and pill <= 0:
                issues.append(f"{where} 的 --r-pill 不是正数（{pill:g}px）")
    return issues


def check() -> Result:
    result = Result("主题契约（四套风格 × 深/浅）")
    if not TOKENS.is_file():
        result.fail("找不到 frontend/src/styles/tokens.css")
        return result
    tokens = contract_tokens()
    if len(tokens) < 20:
        result.fail(f"令牌清单只有 {len(tokens)} 个，看起来没读对")
        return result

    for theme in THEMES:
        path = STYLES / "themes" / f"{theme}.tokens.css"
        if not path.is_file():
            result.fail(f"缺少主题文件：{path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        for light, label in ((False, "深色"), (True, "浅色")):
            declared = theme_block(text, theme, light)
            if declared is None:
                result.fail(f"{theme} 缺少{label}块（[data-style=\"{theme}\"]"
                            + ('[data-theme="light"]' if light else "") + "）")
                continue
            missing = [name for name in tokens if name not in declared]
            if missing:
                result.fail(f"{theme} · {label} 缺 {len(missing)} 个令牌："
                            + ", ".join(missing[:6]) + ("…" if len(missing) > 6 else ""))
        for selector, body in _BLOCK.findall(text):
            for name in _DECL.findall(body):
                if not name.startswith("--"):
                    result.fail(f"{path.name} 里出现了非自定义属性：{name}")

    for theme in THEMES:
        # 一套主题可以有多张皮肤（主题签名 + 按钮语言…），逐张查行数与作用域
        paths = sorted((STYLES / "themes").glob(f"{theme}*.skin.css"))
        if not any(p.name == f"{theme}.skin.css" for p in paths):
            result.fail(f"缺少主题签名皮肤：themes/{theme}.skin.css")
            continue
        for path in paths:
            text = path.read_text(encoding="utf-8")
            lines = [row for row in text.split("\n") if row.strip()]
            if len(lines) > SKIN_MAX_LINES:
                result.fail(f"{path.name} 有 {len(lines)} 行，超过 {SKIN_MAX_LINES} 行上限")
            for selector, _ in _BLOCK.findall(text):
                sel = selector.strip()
                if sel.startswith("@") or not sel:
                    continue
                if f'[data-style="{theme}"]' not in sel:
                    result.fail(f"{path.name} 的选择器没以 [data-style=\"{theme}\"] 开头："
                                + sel.replace("\n", " ")[:60])

    for issue in baseline_issues():
        result.fail(issue)

    for issue in radius_issues():
        result.fail(issue)

    for issue in value_issues():
        result.fail(issue)

    if not result.failures:
        result.note(f"{len(THEMES)} 套主题 × 深/浅 = {len(THEMES) * 2} 个块，"
                    f"每块补齐 {len(tokens)} 个令牌")
        result.note(f"共享布局层的圆角全部来自令牌（{'、'.join(RADIUS_FILES)}）")
        result.note("令牌值域：--s-floor 60–95%、--fx-blur 只有极光非零、--r-* 单调不减")
        result.note(f"主题截图基线 {len(BASELINE_MATRIX) * len(BASELINE_SCREENS)} 张指纹齐全"
                    f"（{BASELINE.relative_to(ROOT)}）")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
