"""把 domain 里的实测 hook 记录导出成内置规则包（P6，ADR-0008）。

用法：
    python tools\\export_engine_rules.py            # 只对比，不写文件
    python tools\\export_engine_rules.py --write    # 写入 aurora/rules/engines/*.json

单一数据源是 `aurora/domain/engine_rules.py` 的 `WILLPLUS_AUTO_HOOKS`
（常量里已经有 date / sample / game / note，导出只是换一种表示），
所以「文档里写了、规则包里没有」这种漂移会被离线检查挡住。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aurora.domain import engine_rules  # noqa: E402

RULES_DIR = ROOT / "aurora" / "rules" / "engines"
PACKAGE = RULES_DIR / "hooks.json"
SCHEMA = "aurora.engine-rules/1"
DOC = ROOT / "docs" / "engines.md"
BEGIN = "<!-- generated:engine-rules -->"
END = "<!-- /generated:engine-rules -->"


def _rule_id(row: dict) -> str:
    """稳定 id：引擎名小写 + exe 名 + 字节数（同一条规则永远同名）。"""
    engine = str(row.get("engine") or "unknown").lower()
    engine = "".join(ch if ch.isalnum() else "-" for ch in engine).strip("-")
    name = str(row["name"]).rsplit(".", 1)[0].lower()
    name = "".join(ch if ch.isalnum() else "-" for ch in name).strip("-")
    return f"{engine}-{name}-{int(row['size'])}"


def build_package() -> dict:
    rules = []
    for row in engine_rules.WILLPLUS_AUTO_HOOKS:
        engine = str(row.get("engine") or _guess_engine(row))
        profile = engine_rules.profile_for(engine)
        codepage = row.get("codepage")
        rules.append({
            "id": _rule_id({**row, "engine": engine}),
            "fingerprint": {
                "name": row["name"],
                "size": int(row["size"]),
                "crc32": f"0x{int(row['crc32']):08X}",
            },
            "engine": engine,
            "hook_code": {
                "mode": str(row.get("mode") or "Q"),
                "offset": int(row.get("offset") or 0),
                "rva": f"0x{int(row['rva']):X}",
                "module": "<exe>",
                "codepage": int(codepage) if codepage else None,
            },
            "text": {
                "encoding": "utf-8" if int(codepage or 0) == 65001 else "utf-16",
                "codepage": int(codepage) if codepage else None,
            },
            "profile": profile,
            "evidence": {
                "date": row.get("date") or "",
                "game": row.get("game") or "",
                "sample": row.get("sample") or "",
                "note": " ".join(str(row.get("note") or "").split()),
            },
        })
    return {"schema": SCHEMA, "rules": rules}


def _guess_engine(row: dict) -> str:
    """老常量没写 engine 字段时按名字猜（advhd→WillPlus、amakano→Artemis/Emote）。"""
    name = str(row.get("name") or "").lower()
    if "advhd" in name or "willplus" in name:
        return "WillPlus"
    if "amakano" in name or "emote" in name:
        return "Artemis/Emote"
    return "unknown"


def render(package: dict) -> str:
    return json.dumps(package, ensure_ascii=False, indent=2) + "\n"


def render_doc_block(package: dict) -> str:
    """docs/engines.md 里的规则包表格（一条规则一行，勿手改）。"""
    lines = [
        BEGIN,
        "| 引擎 | 实测作品 | 结论 | 规则 / 证据 |",
        "| --- | --- | --- | --- |",
    ]
    for rule in package["rules"]:
        ev = rule.get("evidence") or {}
        hook = rule["hook_code"]
        page = f"{hook['codepage']}#" if hook.get("codepage") else ""
        offset = int(hook.get("offset") or 0)
        sign = "-" if offset < 0 else ""
        code = (f"H{hook['mode']}{page}{sign}{abs(offset):X}"
                f"@{int(str(hook['rva']), 16):X}:<exe 文件名>")
        note = " ".join(str(ev.get("note") or "").split())
        lines.append(
            f"| **{rule['engine']}** | {ev.get('game') or '—'} | ✅ 可用（实测 hook 码 "
            f"`{code}`） | 规则 `{rule['id']}` · {ev.get('date') or '—'} 实测"
            f"（样例：`{ev.get('sample') or '—'}`）；用户可在 `data/rules/engines/*.json` 里"
            f"按指纹覆盖。{note} |")
    lines.append(END)
    return "\n".join(lines)


def replace_doc_block(text: str, block: str) -> str:
    """把 docs/engines.md 里两个标记之间的内容换成新生成的块。"""
    if BEGIN in text and END in text:
        head, _, rest = text.partition(BEGIN)
        _, _, tail = rest.partition(END)
        return head + block + tail
    return text.rstrip() + "\n\n## 规则包生成表（由内置规则包生成，勿手改）\n\n" + block + "\n"


def main() -> int:
    package = build_package()
    text = render(package)
    block = render_doc_block(package)
    current = PACKAGE.read_text(encoding="utf-8") if PACKAGE.exists() else ""
    doc = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    doc_ok = block in doc
    if text == current and doc_ok:
        print(f"内置规则包与文档块都已是最新（{len(package['rules'])} 条规则）")
        return 0
    if "--write" not in sys.argv:
        print("规则包 / 文档块需要刷新（加 --write 写入）：")
        print(f"  规则包：{PACKAGE.relative_to(ROOT)}（{'已同步' if text == current else '待更新'}）")
        print(f"  文档块：{DOC.relative_to(ROOT)}（{'已同步' if doc_ok else '待更新'}）")
        return 1
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    PACKAGE.write_text(text, encoding="utf-8", newline="\n")
    DOC.write_text(replace_doc_block(doc, block), encoding="utf-8", newline="\n")
    print(f"已写入 {PACKAGE.relative_to(ROOT)} 与 {DOC.relative_to(ROOT)}"
          f"（{len(package['rules'])} 条规则）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
