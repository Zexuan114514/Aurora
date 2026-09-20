"""分层守卫：今天只拦得住的事先拦，`aurora/` 落地后自动启用全部规则（ADR-0001/0002）。"""
from __future__ import annotations

import ast
import sys

from common import ROOT, Result, imports_of, main, read_text

DOMAIN_FORBIDDEN_IMPORTS = {
    "ctypes", "webview", "subprocess", "socket", "http", "sqlite3", "threading",
    "multiprocessing", "urllib", "winreg", "shutil",
}
DOMAIN_FORBIDDEN_CALLS = {"open", "eval", "exec"}


def _walk(package: str):
    base = ROOT / package
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def check() -> Result:
    result = Result("分层守卫")

    # 规则 1（今天生效）：除入口与 tools 外，任何模块不得改写 sys.path
    offenders = []
    for path in _walk("gl"):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in {"insert", "append"} \
                    and isinstance(node.func.value, ast.Attribute) \
                    and node.func.value.attr == "path":
                offenders.append(path.relative_to(ROOT).as_posix())
    if offenders:
        result.fail(f"以下模块改写了 sys.path（只允许 main.py / tools）：{', '.join(sorted(set(offenders)))}")
    else:
        result.note("sys.path 只在 main.py 里改写")

    # 规则 2（今天生效）：前端不得绕过 call() 直接摸 pywebview.api
    app_js = read_text("gl/web/app.js")
    direct = [line.strip()[:60] for line in app_js.splitlines()
              if "pywebview.api." in line and "const api = ()" not in line]
    if direct:
        result.fail(f"app.js 里存在绕过 call() 的桥接调用：{direct[:3]}")
    else:
        result.note("app.js 全部桥接调用都走 call() 包装")

    # 规则 3-5（P1 起生效）：aurora/ 落地后检查目标分层
    if not (ROOT / "aurora").exists():
        result.note("aurora/ 尚未创建，待激活规则：domain 纯净性、ui/app 不得 import infra、"
                    "只有 bootstrap 装配适配器")
        return result

    domain_files = _walk("aurora/domain")
    for path in domain_files:
        rel = path.relative_to(ROOT).as_posix()
        for name in imports_of(path):
            if name in DOMAIN_FORBIDDEN_IMPORTS or name in {"infra", "ui", "platform"}:
                result.fail(f"{rel} 违反 domain 纯净性：import {name}")
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in DOMAIN_FORBIDDEN_CALLS:
                result.fail(f"{rel} 在 domain 里调用了 {node.func.id}()")

    for package in ("aurora/ui", "aurora/app"):
        for path in _walk(package):
            rel = path.relative_to(ROOT).as_posix()
            for name in imports_of(path):
                if name == "infra":
                    result.fail(f"{rel} 直接 import 了 infra（必须经端口注入）")

    wiring = []
    for path in _walk("aurora"):
        if path.name == "bootstrap.py":
            continue
        if "infra" in imports_of(path):
            wiring.append(path.relative_to(ROOT).as_posix())
    if wiring:
        result.note(f"已迁移代码里 import infra 的文件 {len(wiring)} 个（应随 P3 收敛到 bootstrap）")

    result.note(f"aurora/ 规则已启用：domain {len(domain_files)} 个文件，ui/app/infra 定向检查完成")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
