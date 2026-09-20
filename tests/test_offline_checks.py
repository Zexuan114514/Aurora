"""pytest 包装：把 tools/checks 下的离线检查接进标准测试流程。

设计上检查本体只用标准库（`python tools\\checks\\run_all.py` 即可），
pytest 只是给 CI 与本地开发提供统一的报告格式。
"""
from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKS_DIR = ROOT / "tools" / "checks"
if str(CHECKS_DIR) not in sys.path:
    sys.path.insert(0, str(CHECKS_DIR))

CHECKS = (
    "check_contract",
    "check_dependencies",
    "check_fixture",
    "check_tools_manifest",
    "check_architecture_baseline",
    "check_layers",
)


@pytest.mark.parametrize("name", CHECKS)
def test_offline_check(name: str) -> None:
    module = importlib.import_module(name)
    result = module.check()
    assert result.ok, "\n".join(result.failures) or f"{name} 失败"


def test_repo_root_is_detected() -> None:
    """检查脚本默认从仓库根跑；这里确认路径推导没被改动破坏。"""
    assert (ROOT / "main.py").is_file()
    assert (ROOT / "docs" / "architecture" / "contracts" / "bridge-contract.json").is_file()
