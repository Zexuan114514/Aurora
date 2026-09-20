"""启动冒烟：在临时数据目录里构造一次 Api() 并干净关停。

真机教训：P3.8 的服务化改动让 `Api.__init__` 的装配顺序出错（_vn_engine 晚于 _launch），
打包出的 exe 一启动就 AttributeError —— 这个检查就是为这类「装配期崩溃」兜底。
CI 上没有 pywebview 时自动跳过（用子进程跑，避免污染本进程的 config 路径）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from common import ROOT, Result, main

SCRIPT = (
    "import sys; sys.path.insert(0, r'%s');"
    "from gl.api import Api; api = Api(); print('SERVICES', len(api._tasks.stats()['known'])); api.shutdown()"
)


def check() -> Result:
    result = Result("启动冒烟（Api 装配）")
    try:
        import webview  # noqa: F401
    except Exception:
        result.note("本机没有 pywebview，跳过（CI 场景）")
        return result
    with tempfile.TemporaryDirectory(prefix="aurora-startup-") as tmp:
        env = {**os.environ, "AURORA_DATA": tmp, "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run([sys.executable, "-c", SCRIPT % str(ROOT)], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env, cwd=str(ROOT),
                              timeout=180)
    if proc.returncode != 0:
        result.fail("Api() 装配/关停失败：" + (proc.stderr or proc.stdout or "")[-600:])
        return result
    result.note("Api() 构造 + 七个服务装配 + shutdown 全部正常")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
