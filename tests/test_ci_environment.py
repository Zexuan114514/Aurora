"""CI 环境回归：英文 code page 下离线检查必须照样跑通。

2026-09-20 的 offline-checks 就是这样挂的：脚本打印中文，runner 的 code page
编不出这些字符 → UnicodeEncodeError → 退出码 1。这里用 `PYTHONIOENCODING=cp437`
复现同一个条件，确保修复不会被回退。
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_ALL = ROOT / "tools" / "checks" / "run_all.py"


def test_offline_checks_survive_non_utf8_console() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "cp437"}
    proc = subprocess.run(
        [sys.executable, str(RUN_ALL)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(ROOT), timeout=300,
    )
    assert proc.returncode == 0, (
        "离线检查在非 UTF-8 控制台下失败了（CI 就是这种环境）：\n"
        f"--- stdout ---\n{proc.stdout[-2000:]}\n--- stderr ---\n{proc.stderr[-2000:]}"
    )
    assert "合计 6 项检查" in proc.stdout
