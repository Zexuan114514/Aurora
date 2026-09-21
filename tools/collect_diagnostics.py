"""生成诊断包（不打界面）：python tools\\collect_diagnostics.py [--out 路径] [--json]

和界面上的「设置 → 关于 → 导出诊断包…」走同一个服务（aurora/app/services/diagnostics.py）：
版本 / 环境 / 数据目录计数 / 迁移计划 / 插件与资料源状态 / 脱敏设置 / 日志尾巴。
默认写到 `<数据目录>/diagnostics/Aurora-diagnostics-<时间戳>.zip`。
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


def main() -> int:
    from aurora.app.services.diagnostics import DiagnosticsService
    from aurora.app.services.plugins import PluginsService
    from gl import config
    from gl.sources import SourceManager
    from gl.store import Library

    library = Library()
    plugins = PluginsService(config.DATA_DIR, logger=config.log)
    sources = SourceManager(library)
    sources.set_plugin_statuses(plugins.statuses())
    service = DiagnosticsService(library=library, plugins_service=plugins, sources=sources,
                                 root=config.DATA_DIR, logger=config.log,
                                 version=config.VERSION)

    out = None
    if "--out" in sys.argv:
        index = sys.argv.index("--out")
        if index + 1 >= len(sys.argv):
            print("--out 后面要跟一个文件路径")
            return 2
        out = Path(sys.argv[index + 1])
    result = service.build(out_path=out)
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        print(f"诊断包生成失败：{result.get('error')}")
        return 1
    size_kb = result["bytes"] / 1024
    print(f"诊断包已生成：{result['path']}（{size_kb:.1f} KB，{len(result['entries'])} 个条目）")
    print("里面：summary.json（环境 / 计数 / 插件与资料源状态）、settings.json（脱敏）、logs/（日志尾巴）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
