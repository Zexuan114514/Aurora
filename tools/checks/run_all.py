r"""跑完全部离线检查（无需网络、无需游戏、无需界面）。

用法：
    python tools\checks\run_all.py                 # 全部检查
    python tools\checks\run_all.py --json out.json # 额外写出机器可读结果
"""
from __future__ import annotations

import importlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import Result, report      # noqa: E402

CHECKS = (
    "check_contract",
    "check_dependencies",
    "check_fixture",
    "check_tools_manifest",
    "check_architecture_baseline",
    "check_bridge_targets",
    "check_engine_rules",
    "check_layers",
    "check_packaging",
    "check_startup",
)


def run() -> list[Result]:
    results = []
    for name in CHECKS:
        module = importlib.import_module(name)
        try:
            results.append(module.check())
        except Exception as exc:                       # noqa: BLE001 - 检查本身崩了也要报出来
            broken = Result(name)
            broken.fail(f"检查崩溃：{type(exc).__name__}: {exc}")
            results.append(broken)
    return results


def main() -> int:
    results = run()
    code = report(list(results), "Aurora 离线检查（P0 基线）")
    if "--json" in sys.argv:
        target = pathlib.Path(sys.argv[sys.argv.index("--json") + 1])
        payload = {
            "checks": [
                {"name": r.name, "ok": r.ok, "failures": r.failures,
                 "warnings": r.warnings, "notes": r.notes}
                for r in results
            ],
            "ok": code == 0,
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"（结果已写入 {target}）")
    return code


if __name__ == "__main__":
    sys.exit(main())
