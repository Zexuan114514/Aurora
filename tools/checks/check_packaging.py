"""打包清单守卫：build_exe.py 里的前端清单必须与 gl/web 实际目录一致。

P4 的交付里有一条「打包清单单一来源」：清单只有 `tools/build_exe.py`
顶部的 WEB_FILES / WEB_MODULE_DIRS / WEB_USER_DIRS 一份，本检查负责证明它没漏东西 ——

  * 清单里写的文件/目录必须真的存在
  * `gl/web` 顶层**不允许有未登记的文件或目录**（漏登记 = 打包后页面 404）

用户素材 P5 起不再进 web 目录（由 aurora/infra/webserver.py 按 /assets/ 服务 data/ 下的原图），
但仍兼容老的 WEB_USER_DIRS 列表：若 build_exe.py 里还有这一项，就按「只留目录、不进包」检查。
"""
from __future__ import annotations

import ast
import re
import sys

from common import ROOT, Result, main

BUILD = "tools/build_exe.py"
WEB = "gl/web"
OVERLAY = "aurora/ui/overlay.py"


def _overlay_entry() -> str:
    """从 `aurora/ui/overlay.py` 里读出 `HTML_PATH` 的字面量相对路径。

    只做静态读取（不 import 应用代码 —— 离线检查不允许依赖 pywebview）。
    """
    match = re.search(r"^HTML_PATH\s*=\s*config\.WEB_DIR\s*/\s*(.+)$",
                      (ROOT / OVERLAY).read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        return ""
    parts = re.findall(r'"([^"]+)"', match.group(1))
    return "/".join(parts)


def _tuple_literals(source: str, *names: str) -> dict[str, tuple[str, ...]]:
    """把 build_exe.py 里那几个清单常量的字面量读出来（用 AST，不执行脚本）。"""
    found: dict[str, tuple[str, ...]] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                try:
                    found[target.id] = tuple(ast.literal_eval(node.value))
                except (ValueError, SyntaxError):
                    pass
    return found


def check() -> Result:
    result = Result("打包清单（前端）")
    build_py = ROOT / BUILD
    web = ROOT / WEB
    if not build_py.is_file() or not web.is_dir():
        result.fail(f"找不到 {BUILD} 或 {WEB}")
        return result

    literals = _tuple_literals(build_py.read_text(encoding="utf-8"),
                               "WEB_FILES", "WEB_MODULE_DIRS", "WEB_USER_DIRS")
    missing_const = [n for n in ("WEB_FILES", "WEB_MODULE_DIRS") if n not in literals]
    if missing_const:
        result.fail(f"{BUILD} 里读不到清单常量：{', '.join(missing_const)}")
        return result

    files = literals["WEB_FILES"]
    module_dirs = literals["WEB_MODULE_DIRS"]
    user_dirs = literals.get("WEB_USER_DIRS", ())

    for name in files:
        if not (web / name).is_file():
            result.fail(f"清单里的前端文件不存在：{WEB}/{name}")
    for name in module_dirs:
        if not (web / name).is_dir():
            result.fail(f"清单里的前端模块目录不存在：{WEB}/{name}")
    for name in user_dirs:
        if not (web / name).is_dir():
            result.fail(f"清单里的用户素材目录不存在：{WEB}/{name}")

    on_disk_files, on_disk_dirs = set(), set()
    for path in web.iterdir():
        if path.name.startswith(".") or path.name == "__pycache__":
            continue
        (on_disk_dirs if path.is_dir() else on_disk_files).add(path.name)

    unlisted_files = sorted(on_disk_files - set(files))
    if unlisted_files:
        result.fail(f"{WEB} 下有没写进打包清单的文件：{', '.join(unlisted_files)}"
                    f"（补进 {BUILD} 的 WEB_FILES，否则打包后 404）")
    unlisted_dirs = sorted(on_disk_dirs - set(module_dirs) - set(user_dirs))
    if unlisted_dirs:
        result.fail(f"{WEB} 下有没写进打包清单的目录：{', '.join(unlisted_dirs)}"
                    f"（模块树补进 WEB_MODULE_DIRS，用户素材补进 WEB_USER_DIRS）")

    packed_files = len(files) + sum(1 for d in module_dirs
                                    for _ in (web / d).rglob("*") if _.is_file())
    note = (f"前端清单：{len(files)} 个顶层文件 + {len(module_dirs)} 棵模块树"
            f"（共 {packed_files} 个文件）")
    if user_dirs:
        note += f"，{len(user_dirs)} 个用户素材目录不进包"
    else:
        note += "；用户素材不在 web 目录（由 /assets/ 直接服务 data/，P5）"
    result.note(note)
    if not unlisted_files and not unlisted_dirs:
        result.note("gl/web 顶层无未登记条目：清单与实际目录一致")

    # v2（Vite 产物）的形状断言：入口 + bundle 里至少一个 js / css + 构建指纹
    v2 = web / "v2"
    if (v2 / "index.html").is_file():
        js = list((v2 / "bundle").glob("*.js")) if (v2 / "bundle").is_dir() else []
        css = list((v2 / "bundle").glob("*.css")) if (v2 / "bundle").is_dir() else []
        if not js or not css:
            result.fail("gl/web/v2/bundle 下缺少 js / css 产物（先跑 npm run build）")
        for name in ("overlay.html", "build-info.json"):
            if not (v2 / name).is_file():
                result.fail(f"gl/web/v2/{name} 不存在（先跑 npm run build）")
        result.note(f"v2 产物：{len(js)} 个 js + {len(css)} 个 css + 构建指纹")

    # 运行时的入口常量必须落在实际产物上：P8.9 删 v1 时 overlay.py 还指着
    # `gl/web/overlay.html`，离线门全绿、真机上悬浮窗直接不出现（e2e 才抓到）。
    entry = _overlay_entry()
    if not entry:
        result.fail(f"{OVERLAY} 里找不到 HTML_PATH（入口守卫失效，请同步这条检查）")
    elif not (web / entry).is_file():
        result.fail(f"悬浮窗入口不存在：{WEB}/{entry}（{OVERLAY} 的 HTML_PATH）")
    else:
        result.note(f"悬浮窗入口：{WEB}/{entry}")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
