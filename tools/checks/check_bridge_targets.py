"""桥接转发守卫：`self._服务.方法(...)` 里的方法必须真的存在。

血泪教训（P3.8-a）：`SettingsService` 把 `set_setting` 改名成 `set`，但桥接层还
在调 `self._settings.set_setting(...)` —— 设置页每次保存都抛 AttributeError，
而契约守卫只看桥接层自己的方法名，完全看不出来。这个检查把桥接 mixin 里**所有
`self._x.y(...)` 形式的一行转发**都解析出来，对着服务类的真实属性核一遍。
"""
from __future__ import annotations

import ast

from common import ROOT, Result, main, read_text

#: 桥接层里用到的服务属性 → 该服务的实现文件（相对项目根）
SERVICE_MODULES = {
    "aurora/app/services/settings.py": "SettingsService",
    "aurora/app/services/library.py": "LibraryService",
    "aurora/app/services/metadata.py": "MetadataService",
    "aurora/app/services/vntext.py": "VnTextService",
    "aurora/app/services/hooksearch.py": "HookSearchService",
    "aurora/app/services/launch.py": "LaunchService",
    "aurora/app/services/translation.py": "TranslationService",
}

#: 非服务对象（引擎/门面）也一起核，属性名 → 类型来自 gl/api.py 的装配
EXTRA_TARGETS = {
    "_vn_engine": "aurora/infra/vntext.py:VnTextEngine",
    "_overlay": "aurora/ui/overlay.py:Overlay",
}


def _class_methods(rel_path: str, class_name: str) -> set[str]:
    path = ROOT / rel_path
    if not path.exists():
        return set()
    tree = ast.parse(read_text(rel_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            names = set()
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(child.name)
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
            return names
    return set()


def _api_services() -> dict[str, str]:
    """从 gl/api.py 的 __init__ 里读「属性名 → 服务实现文件」的装配关系。"""
    tree = ast.parse(read_text("gl/api.py"))
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Attribute):
            continue
        target = node.targets[0]
        if not (isinstance(target.value, ast.Name) and target.value.id == "self"):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        callee = value.func
        name = callee.attr if isinstance(callee, ast.Attribute) else \
            (callee.id if isinstance(callee, ast.Name) else "")
        for rel, cls in SERVICE_MODULES.items():
            if name == cls:
                mapping[target.attr] = f"{rel}:{cls}"
    return mapping


def check() -> Result:
    result = Result("桥接转发目标")
    services = _api_services()
    services.update(EXTRA_TARGETS)
    cache: dict[str, set[str]] = {}
    problems: list[str] = []
    checked = 0
    # 扫桥接 mixin + 装配根（gl/api.py 里也有 self._x.y(...) 形式的转发）
    targets = sorted((ROOT / "aurora/ui/bridge").rglob("*.py"))
    api_file = ROOT / "gl/api.py"
    if api_file.exists():
        targets.append(api_file)
    for path in targets:
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if not (isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name)
                    and owner.value.id == "self"):
                continue
            attr = owner.attr
            if attr not in services:
                continue
            rel_cls = services[attr]
            rel, _, cls = rel_cls.partition(":")
            if rel_cls not in cache:
                cache[rel_cls] = _class_methods(rel, cls)
            if not cache[rel_cls]:
                continue
            checked += 1
            if node.func.attr not in cache[rel_cls]:
                problems.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} "
                                f"self.{attr}.{node.func.attr}() 在 {cls} 里不存在")
    if problems:
        result.fail("桥接调用了不存在的服务方法：\n    " + "\n    ".join(problems))
    else:
        result.note(f"核对 {checked} 处服务转发，全部存在")
    return result


if __name__ == "__main__":
    sys_exit = main(check)
    raise SystemExit(sys_exit)
