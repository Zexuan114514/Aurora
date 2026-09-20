"""离线检查的公共工具（只用标准库）。

每个 check_*.py 暴露 `check() -> Result`，也可以直接当脚本跑（失败时退出码 1）。
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _force_utf8_console() -> None:
    """把标准输出切到 UTF-8。

    检查脚本的标题与结论是中文；在英文 code page 的机器上（GitHub Actions 的
    windows-latest 就是），`print` 会抛 UnicodeEncodeError 让检查整批失败。
    这里主动 reconfigure，跑在 pytest 捕获里时（没有 reconfigure）静默跳过。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
        except Exception:
            pass


_force_utf8_console()


class Result:
    """一次检查的结果：失败项会阻断 CI，告警只提示。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    @property
    def ok(self) -> bool:
        return not self.failures

    def render(self) -> str:
        head = f"[{'PASS' if self.ok else 'FAIL'}] {self.name}"
        lines = [head]
        for item in self.failures:
            lines.append(f"  x {item}")
        for item in self.warnings:
            lines.append(f"  ! {item}")
        for item in self.notes:
            lines.append(f"  - {item}")
        return "\n".join(lines)


def load_json(path: pathlib.Path | str) -> object:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def read_text(path: pathlib.Path | str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="ignore")


def python_files(*roots: str) -> list[pathlib.Path]:
    """收集源码文件（跳过 __pycache__）。"""
    found: list[pathlib.Path] = []
    for root in roots:
        base = ROOT / root
        candidates = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for path in candidates:
            if "__pycache__" in path.parts or not path.is_file():
                continue
            found.append(path)
    return found


def _module_file(module: str) -> pathlib.Path | None:
    """把 `a.b.c` 映射到仓库里的 a/b/c.py 或 a/b/c/__init__.py。"""
    parts = module.split(".")
    candidate = ROOT.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    package = ROOT.joinpath(*parts) / "__init__.py"
    return package if package.is_file() else None


def class_methods(path: pathlib.Path | str, class_name: str,
                  _seen: set[tuple[str, str]] | None = None) -> dict[str, ast.FunctionDef]:
    """返回某个类的方法，**含从基类继承的**（P3 起桥接方法分散在 mixin 里）。

    静态解析：同文件的基类直接递归；`from a.b import Base` 形式的基类按模块名找到文件再递归。
    子类同名方法覆盖基类（与 Python MRO 的直觉一致）。
    """
    seen = _seen if _seen is not None else set()
    full_path = pathlib.Path(path)
    if not full_path.is_absolute():
        full_path = ROOT / full_path
    path = full_path
    key = (str(path), class_name)
    if key in seen:
        return {}
    seen.add(key)

    text = read_text(path)
    tree = ast.parse(text)
    # 名字 → 模块 的映射：`from a.b.c import Base` 之后 `class X(Base)` 才能被解析到文件
    import_map: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:      # 相对导入：按当前文件所在包补全
                base_pkg = pathlib.Path(path).parent.relative_to(ROOT).parts
                prefix = ".".join(base_pkg[:len(base_pkg) - node.level + 1])
                module = f"{prefix}.{module}" if module else prefix
            for alias in node.names:
                import_map[alias.asname or alias.name] = module
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        collected: dict[str, ast.FunctionDef] = {}
        for base in node.bases:
            base_class = None
            base_module = None
            if isinstance(base, ast.Name):
                base_class = base.id
            elif isinstance(base, ast.Attribute):
                base_class = base.attr
                base_module = ast.unparse(base.value)
            if not base_class:
                continue
            if base_module:
                target = _module_file(base_module)
            else:
                owner = import_map.get(base_class, "")
                target = _module_file(owner) if owner else pathlib.Path(path)
            if target is not None:
                collected.update(class_methods(target, base_class, seen))
        for fn in node.body:
            if isinstance(fn, ast.FunctionDef):
                collected[fn.name] = fn           # 子类覆盖
        return collected
    return {}


def function_signature(fn: ast.FunctionDef) -> dict:
    """方法的参数 / 返回标注（用于与契约快照比对）。"""
    params = []
    defaults = fn.args.defaults or []
    default_names = {a.arg for a in fn.args.args[-len(defaults):]} if defaults else set()
    for arg in fn.args.args:
        if arg.arg == "self":
            continue
        params.append({
            "name": arg.arg,
            "type": ast.unparse(arg.annotation) if arg.annotation else "any",
            "required": arg.arg not in default_names,
        })
    return {
        "params": params,
        "returns": ast.unparse(fn.returns) if fn.returns else "any",
    }


def imports_of(path: pathlib.Path) -> set[str]:
    """模块里出现的顶层 import 名（含 `from x import y` 的 x）。"""
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:      # 相对导入属于本包
                continue
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def frontend_calls(js_path: pathlib.Path | str) -> set[str]:
    """前端通过 call("name") 调用的桥接方法名。"""
    import re

    return set(re.findall(r'call\(\s*"([a-z_]+)"', read_text(js_path)))


def emitted_topics(*paths: pathlib.Path | str) -> set[str]:
    """后端 emit 过的主题名。"""
    import re

    topics: set[str] = set()
    for path in paths:
        for match in re.finditer(r'_emit\(\s*"([a-z:_-]+)"', read_text(path)):
            topics.add(match.group(1))
    return topics


def report(results: Iterable[Result], title: str = "Aurora 离线检查") -> int:
    """打印汇总并返回进程退出码。"""
    results = list(results)
    failed = [r for r in results if not r.ok]
    print(f"== {title} ==")
    for result in results:
        print(result.render())
    print(f"== 合计 {len(results)} 项检查：通过 {len(results) - len(failed)}，失败 {len(failed)} ==")
    return 1 if failed else 0


def main(check) -> int:      # noqa: ANN001 - 供各 check 脚本直接调用
    return report([check()])


if __name__ == "__main__":   # pragma: no cover - 手动调用入口
    sys.exit(main(lambda: Result("common")))
