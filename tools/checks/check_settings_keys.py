"""设置键名守卫：前端写过去的每个设置键，后端都必须认得。

起因是 v2 迁移时踩的坑：界面上「上下文句数 / 自动开启 / 悬浮窗字号 / 不透明度」
四个控件写的是 `vntext_context` / `vntext_auto` / `{fontSize}` / `{alpha}`，
后端只认 `vntext_context_lines` / `vntext_auto_start` / `{font}` / `{opacity}`，
于是「能拖、能点，但设置没落盘」，e2e 与截图都看不出来。

规则很简单，真相在 `aurora/infra/config.py` 的 DEFAULT_SETTINGS：
  1. 前端用 set_setting / 相关封装写过去的键，都必须在 DEFAULTS 里；
  2. 写给悬浮窗外观的字段，必须是 `vntext_overlay` 里已有的字段；
  3. 写过去的值如果出现在 `vntext_engine` 这类枚举里，必须在枚举内（见 vntext 服务）。
  4. 界面上滑杆的取值范围不能超出后端的 clamp 区间 —— 后端是**静默夹**，
     越界不报错，只把值改小/改大（所以滑杆跑出去了没人会发现）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from common import ROOT, Result, main

SRC = ROOT / "frontend" / "src"
SUFFIXES = {".vue", ".ts"}

#: 前端把设置写回后端的几种写法（键名写成字面量才算数，变量形式的跳过）
KEY_PATTERNS = (
    re.compile(r"""call\(\s*['"]set_setting['"]\s*,\s*['"]([a-z0-9_]+)['"]""", re.I),
    re.compile(r"""saveSetting\(\s*['"]([a-z0-9_]+)['"]""", re.I),
    re.compile(r"""call\(\s*['"]set_vntext_option['"]\s*,\s*['"]([a-z0-9_]+)['"]""", re.I),
    re.compile(r"""saveVn\(\s*['"]([a-z0-9_]+)['"]""", re.I),
    re.compile(r"""call\(\s*['"]set_proxy_option['"]\s*,\s*['"]([a-z0-9_]+)['"]""", re.I),
    re.compile(r"""saveProxy\(\s*['"]([a-z0-9_]+)['"]""", re.I),
    re.compile(r"""call\(\s*['"]set_locale_option['"]\s*,\s*['"]([a-z0-9_]+)['"]""", re.I),
)

#: 悬浮窗外观传的是对象字面量，字段名要在 vntext_overlay 里
#: （两种写法都认：直接 call("set_overlay_style", {...})，或页面的 saveOverlay({...}) 包装）
OVERLAY_PATTERN = re.compile(
    r"""(?:set_overlay_style['"]\s*,\s*|saveOverlay\(\s*)\{([^}]*)\}""", re.S)
PROPERTY = re.compile(r"""([A-Za-z_][A-Za-z0-9_]*)\s*:""")

#: 取词方式的取值表（与 aurora/app/services/vntext.py 的 allowed 判定一致）
ENGINE_VALUES = {"auto", "hook", "ocr"}

#: 滑杆 id → (后端字段, 最小值, 最大值)。区间取自后端：
#:   vntext_context_lines —— aurora/infra/linetrans.py 里 clamp 到 0..12
#:   vntext_overlay.font / .opacity —— aurora/ui/overlay.py 的 set_style clamp 12..40 / 0.35..1.0
SLIDER_DOMAINS = {
    "setVnContext": ("vntext_context_lines", 0, 12),
    "setVnFont": ("vntext_overlay.font", 12, 40),
    "setVnOpacity": ("vntext_overlay.opacity", 35, 100),
}
SLIDER_TAG = re.compile(
    r"""<el-slider\b[^>]*?id=['"]([A-Za-z0-9_]+)['"][^>]*?>""", re.S)
RANGE = re.compile(r':(min|max)="(-?\d+)"')


def frontend_files() -> list[Path]:
    return sorted(path for path in SRC.rglob("*")
                  if path.is_file() and path.suffix in SUFFIXES)


def written_keys() -> dict[str, set[str]]:
    """键名 → 出现它的文件（去掉注释里的说明文字，只看真实调用）。"""
    found: dict[str, set[str]] = {}
    for path in frontend_files():
        text = path.read_text(encoding="utf-8")
        for pattern in KEY_PATTERNS:
            for match in pattern.finditer(text):
                found.setdefault(match.group(1), set()).add(
                    path.relative_to(ROOT).as_posix())
    return found


def overlay_fields() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in frontend_files():
        text = path.read_text(encoding="utf-8")
        for match in OVERLAY_PATTERN.finditer(text):
            for name in PROPERTY.findall(match.group(1)):
                found.setdefault(name, set()).add(path.relative_to(ROOT).as_posix())
    return found


def engine_values() -> dict[str, set[str]]:
    """主题 / 设置里的取词方式下拉值（`value="hook"` 这种）。"""
    found: dict[str, set[str]] = {}
    for path in frontend_files():
        if path.suffix != ".vue":
            continue
        text = path.read_text(encoding="utf-8")
        block = re.search(r"""id=['"]setVnEngine['"](.*?)</select>""", text, re.S)
        if not block:
            continue
        for match in re.finditer(r"""value=['"]([a-z]+)['"]""", block.group(1)):
            found.setdefault(match.group(1), set()).add(
                path.relative_to(ROOT).as_posix())
    return found


def slider_ranges() -> dict[str, tuple[int, int, str]]:
    """模板里每个 el-slider 的 (min, max, 文件)。没写 min/max 就是 Element Plus 的 0..100。"""
    found: dict[str, tuple[int, int, str]] = {}
    for path in frontend_files():
        if path.suffix != ".vue":
            continue
        text = path.read_text(encoding="utf-8")
        for match in SLIDER_TAG.finditer(text):
            tag = match.group(0)
            bounds = {key: int(value) for key, value in RANGE.findall(tag)}
            found[match.group(1)] = (bounds.get("min", 0), bounds.get("max", 100),
                                     path.relative_to(ROOT).as_posix())
    return found


def check() -> Result:
    result = Result("设置键名（前端写入 vs 后端 DEFAULTS）")
    sys.path.insert(0, str(ROOT))
    try:
        from aurora.infra.config import DEFAULT_SETTINGS as DEFAULTS
    except Exception as exc:                              # noqa: BLE001
        result.fail(f"读不到 aurora/infra/config.py 的 DEFAULTS：{exc}")
        return result

    known = set(DEFAULTS)
    overlay_known = set(DEFAULTS.get("vntext_overlay") or {})

    keys = written_keys()
    unknown = sorted(name for name in keys if name not in known)
    for name in unknown:
        result.fail("前端写了后端不认识的设置键：" + name
                    + "（出现在 " + ", ".join(sorted(keys[name])) + "）")

    fields = overlay_fields()
    unknown_fields = sorted(name for name in fields if name not in overlay_known)
    for name in unknown_fields:
        result.fail("悬浮窗外观字段后端不认：" + name
                    + "（vntext_overlay 里只有 " + ", ".join(sorted(overlay_known)) + "）")

    values = engine_values()
    for value in sorted(values):
        if value not in ENGINE_VALUES:
            result.fail(f"取词方式下拉出现后端不认的值：{value}"
                        f"（应为 {'/'.join(sorted(ENGINE_VALUES))}）")

    sliders = slider_ranges()
    for name, (field, low, high) in SLIDER_DOMAINS.items():
        if name not in sliders:
            result.fail(f"找不到滑杆 #{name}（它写的是 {field}）")
            continue
        got_min, got_max, where = sliders[name]
        if (got_min, got_max) != (low, high):
            result.fail(f"#{name} 的范围是 {got_min}..{got_max}，后端 {field} 只收 {low}..{high}"
                        f"（越界会被静默夹掉，改 {where} 或改后端）")

    if not result.failures:
        result.note(f"前端写入 {len(keys)} 个设置键 + {len(fields)} 个悬浮窗字段，"
                    f"全部在 config.DEFAULTS 里")
        result.note(f"取词方式取值：{'/'.join(sorted(values))}")
        result.note("滑杆区间与后端 clamp 一致："
                    + " / ".join(f"{name} {sliders[name][0]}..{sliders[name][1]}"
                                 for name in SLIDER_DOMAINS if name in sliders))
    return result


if __name__ == "__main__":
    sys.exit(main(check))
