"""清单守卫：tools/ 下的脚本要在清单里登记，且不许再踩两个已踩过的坑。

四类断言：

1. **登记完整**：`tools/*.py` 逐个在清单里，kind / phase / expected 合法；
2. **控制台自保**：每个脚本都要过 `tools/_common.setup_console()`。否则中文控制台
   下打印带「⋯」的界面文案会抛 UnicodeEncodeError，整批脚本跑一半就死
   （`tools/e2e.py` 实测第 81 步崩，报告停在 80/81）；
3. **不许写死 v1 数据路径**：`data/library.json` / `data/settings.json` 在 P2 之后
   已经不存在（库在 `state/` 下）。实测这让 `check_library` / `vntext_live` /
   `vntext_hookprobe` / `vntext_rawdump` 四个脚本开箱即崩；库路径一律问
   `tools/_common.layout()`；
4. **kind=offline 的脚本真跑一遍**：清单从「元数据」变成「守卫」的关键 ——
   期望写在清单里却没人执行，等于没有（上面第 3 条就是这么漏过去的）。
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys

from common import ROOT, Result, load_json, main, read_text

MANIFEST = "tools/checks/tools-manifest.json"
PHASES = {"P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "—"}

#: 唯一被允许自己拼 v1 路径的文件（它就是路径解析的实现与说明）
PATH_GUARD_EXEMPT = {"_common.py"}

LEGACY_LITERAL_RE = re.compile(r"data[\\/](?:library|settings)\.json")


def _slash_parts(node: ast.AST) -> list[str]:
    """把 `ROOT / "data" / "library.json"` 拆成常量序列（非常量项忽略）。"""
    parts: list[ast.AST] = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        parts.append(node.right)
        node = node.left
    parts.append(node)
    return [item.value for item in reversed(parts)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)]


def _legacy_path_hits(path) -> bool:
    """代码里是不是自己拼了 `data/library.json` 这类 v1 路径。

    只看**代码**：文档字符串与注释里的说明不算（`_common.py` 与 `check_library.py`
    的说明里都写着这条老路径）。两种形态都要认：
      * `Path("data/library.json")` —— 单个字符串常量；
      * `ROOT / "data" / "library.json"` —— `/` 链上的两个常量。
    """
    try:
        tree = ast.parse(read_text(path))
    except SyntaxError:
        return False
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings \
                and LEGACY_LITERAL_RE.search(node.value):
            return True
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        parts = _slash_parts(node)
        for index in range(len(parts) - 1):
            if parts[index] == "data" and parts[index + 1] in {"library.json", "settings.json"}:
                return True
    return False


def _run_offline(rel_path: str, timeout: float = 240.0) -> tuple[bool, str]:
    """真跑一个 kind=offline 脚本；返回（是否通过, 结论行）。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(ROOT / rel_path)],
                              cwd=str(ROOT), env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"{timeout:.0f} 秒超时"
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    tail = lines[-1] if lines else ""
    if proc.returncode != 0:
        crash = (proc.stderr or "").strip().splitlines()
        return False, (tail or (crash[-1] if crash else f"退出码 {proc.returncode}"))
    return True, tail


def check() -> Result:
    result = Result("探针脚本清单")
    manifest = load_json(MANIFEST)
    kinds = set(manifest["kinds"])
    entries = manifest["scripts"]

    listed = [entry["path"] for entry in entries]
    duplicates = sorted({p for p in listed if listed.count(p) > 1})
    if duplicates:
        result.fail(f"清单里有重复登记：{duplicates}")

    for entry in entries:
        path = ROOT / entry["path"]
        if not path.exists():
            result.fail(f"清单登记了不存在的脚本：{entry['path']}")
        if entry["kind"] not in kinds:
            result.fail(f"{entry['path']} 的 kind 非法：{entry['kind']}")
        if entry["phase"] not in PHASES:
            result.fail(f"{entry['path']} 的 phase 非法：{entry['phase']}")
        if not str(entry.get("expected") or "").strip():
            result.fail(f"{entry['path']} 缺少 expected 结论")

    on_disk = sorted(p.relative_to(ROOT).as_posix()
                     for p in (ROOT / "tools").glob("*.py") if p.is_file())
    unlisted = sorted(set(on_disk) - set(listed))
    if unlisted:
        result.fail(f"新增脚本没有登记到清单：{', '.join(unlisted)}")
    gone = sorted(set(listed) - set(on_disk))
    if gone:
        result.fail(f"清单里的脚本已不存在：{', '.join(gone)}")

    # ② 控制台自保 + ③ 不许写死 v1 路径
    missing_console: list[str] = []
    legacy_paths: list[str] = []
    for rel in on_disk:
        text = read_text(rel)
        name = rel.split("/")[-1]
        if name not in PATH_GUARD_EXEMPT and "setup_console()" not in text:
            missing_console.append(name)
        if name not in PATH_GUARD_EXEMPT and _legacy_path_hits(ROOT / rel):
            legacy_paths.append(name)
    if missing_console:
        result.fail("这些脚本没接 tools/_common.setup_console()（中文控制台会崩）："
                    + ", ".join(missing_console))
    if legacy_paths:
        result.fail("这些脚本仍写死 v1 数据路径（P2 之后库在 data/state/ 下）："
                    + ", ".join(legacy_paths))

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    not_documented = [entry["path"].replace("tools/", "") for entry in entries
                      if entry["kind"] in {"offline", "network", "live", "local-process"}
                      and entry["path"].replace("tools/", "") not in readme]
    if not_documented:
        result.warn(f"README 自检脚本小节未提到：{', '.join(not_documented)}")

    # ④ kind=offline 的脚本真跑
    offline = [entry["path"] for entry in entries if entry["kind"] == "offline"]
    for rel in offline:
        ok, tail = _run_offline(rel)
        if ok:
            result.note(f"{rel} 真跑通过：{tail[:90]}")
        else:
            result.fail(f"{rel} 真跑失败：{tail[:160]}")

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    result.note("脚本分类：" + "，".join(f"{k} {v}" for k, v in sorted(counts.items())))
    result.note(f"共 {len(entries)} 个脚本，全部有 kind / phase / expected；"
                f"控制台守卫 {len(on_disk)} 个；真跑 offline {len(offline)} 个")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
