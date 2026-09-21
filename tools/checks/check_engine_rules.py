"""引擎规则包守卫（P6，ADR-0008）。

三条不放过的漂移：
  1. 内置规则包（`aurora/rules/engines/*.json`）必须通过 schema 校验
  2. 规则包必须与 `aurora/domain/engine_rules.py` 的常量一致（导出脚本产物不陈旧）
  3. `docs/engines.md` 的规则包表格必须与规则包一致（文档与代码同源）

不合规时提示怎么修：`python tools/export_engine_rules.py --write`
"""
from __future__ import annotations

import sys

from common import ROOT, Result, main

RULES_DIR = ROOT / "aurora" / "rules" / "engines"


def check() -> Result:
    result = Result("引擎规则包")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    from aurora.infra import rules as rules_mod          # noqa: PLC0415
    import export_engine_rules as exporter              # noqa: PLC0415

    loaded, problems = rules_mod.load_packages([RULES_DIR])
    for problem in problems:
        result.fail(f"内置规则包不合规：{problem}")
    if not loaded:
        result.fail(f"{RULES_DIR.relative_to(ROOT)} 里没有可用的内置规则")
        return result

    package = exporter.build_package()
    # 整包逐字比对（不只 id / 指纹）：改了偏移、档位或证据都算漂移
    expected_text = exporter.render(package)
    disk_text = exporter.PACKAGE.read_text(encoding="utf-8") if exporter.PACKAGE.exists() else ""
    if expected_text != disk_text:
        on_disk = {r["id"] for r in loaded}
        expected_ids = {r["id"] for r in package["rules"]}
        detail = (f"条数 {len(loaded)} → {len(package['rules'])}"
                  if on_disk != expected_ids else "内容有差异（偏移 / 档位 / 证据）")
        result.fail(f"规则包与 domain 常量不一致：{detail}"
                    "（跑 python tools/export_engine_rules.py --write）")

    doc = (ROOT / "docs" / "engines.md").read_text(encoding="utf-8")
    if exporter.render_doc_block(package) not in doc:
        result.fail("docs/engines.md 的规则包表格与规则包不一致"
                    "（跑 python tools/export_engine_rules.py --write）")

    if not result.failures:
        result.note(f"内置规则 {len(loaded)} 条，schema 通过；导出产物与文档表格均与常量一致")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
