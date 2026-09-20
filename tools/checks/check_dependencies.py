"""依赖守卫：运行时只允许 pywebview + winrt + 标准库（ADR-0003）。

区分两种第三方依赖：
  * 模块级 import —— 硬依赖，只允许 pywebview / winrt；
  * 函数内惰性 import —— 可选依赖，必须在 OPTIONAL_RUNTIME 里登记（缺失时要能降级）。
"""
from __future__ import annotations

import ast
import re
import sys

from common import ROOT, Result, imports_of, main, python_files

ALLOWED_RUNTIME = {"webview", "winrt"}
ALLOWED_LOCAL = {"gl", "aurora"}
#: 可选运行时依赖：缺失时必须降级而不是崩（当前 PIL 只在存 PNG / 转 .ico 时用）
OPTIONAL_RUNTIME = {
    "PIL": "screencap 存 PNG 供框选、winapi 把图片转 .ico；缺 Pillow 时功能降级",
}


def _module_level_names(path) -> set[str]:      # noqa: ANN001
    """只取模块级（含顶层 try/if 块）的 import，函数体内的不算。"""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    names: set[str] = set()

    def walk(body: list) -> None:               # noqa: ANN001
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names.add(node.module.split(".")[0])
            for field in ("body", "orelse", "finalbody"):
                sub = getattr(node, field, None)
                if isinstance(sub, list):
                    walk(sub)
            for handler in getattr(node, "handlers", []) or []:
                walk(handler.body)

    walk(tree.body)
    return names


def check() -> Result:
    result = Result("运行时依赖白名单")
    stdlib = set(sys.stdlib_module_names)

    runtime_files = python_files("main.py", "gl")
    hard: dict[str, set[str]] = {}
    optional: dict[str, set[str]] = {}
    for path in runtime_files:
        rel = path.relative_to(ROOT).as_posix()
        module_level = _module_level_names(path)
        for name in module_level:
            if name in stdlib or name in ALLOWED_RUNTIME or name in ALLOWED_LOCAL:
                continue
            hard.setdefault(rel, set()).add(name)
        for name in imports_of(path) - module_level:
            if name in stdlib or name in ALLOWED_RUNTIME or name in ALLOWED_LOCAL:
                continue
            if name not in OPTIONAL_RUNTIME:
                hard.setdefault(rel, set()).add(name)
                continue
            optional.setdefault(rel, set()).add(name)

    for path, names in sorted(hard.items()):
        result.fail(f"{path} 引入了未批准的运行时依赖：{', '.join(sorted(names))}")
    if not hard:
        result.note(f"运行时代码 {len(runtime_files)} 个文件，模块级第三方依赖只有 "
                    f"{', '.join(sorted(ALLOWED_RUNTIME))}")
    for path, names in sorted(optional.items()):
        for name in sorted(names):
            result.note(f"可选依赖 {name}（{path}）：{OPTIONAL_RUNTIME[name]}")

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pinned = []
    for line in requirements.splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        name = re.split(r"[<>=!~\[; ]", text, maxsplit=1)[0].strip().lower()
        pinned.append(name)
        if not (name == "pywebview" or name.startswith("winrt")):
            result.fail(f"requirements.txt 出现白名单外的依赖：{text}")
    if pinned:
        result.note(f"requirements.txt：{', '.join(pinned)}")

    dev = ROOT / "requirements-dev.txt"
    if dev.exists():
        dev_names = [line.split("#", 1)[0].strip() for line in dev.read_text(encoding="utf-8").splitlines()]
        dev_names = [n for n in dev_names if n]
        result.note(f"requirements-dev.txt（不进发布包）：{', '.join(dev_names)}")

    tests_dir = ROOT / "tests"
    if tests_dir.exists():
        for path in sorted(tests_dir.rglob("*.py")):
            names = imports_of(path)
            if names & {"webview"}:
                result.warn(f"{path.relative_to(ROOT).as_posix()} 在测试里 import 了 pywebview，"
                            f"离线测试应使用端口替身")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
