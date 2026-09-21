"""诊断包（P7）：把排错要看的东西收成一个 zip。

打包内容（zip 内一层同名目录）：

    README.txt        里面是什么、隐私怎么处理、怎么发给维护者
    summary.json      版本 / 环境 / 数据目录 / 计数 / 迁移计划 / 插件状态 / 资料源状态
    settings.json     设置快照（脱敏：Key / token / password 类字段一律打码，URL 里的账密也抹掉）
    logs/*.log        日志尾部（每个文件最多 256 KB，最多 5 个）

**不收集**：游戏可执行文件、素材原图、游戏库全文（那属于游戏库导出，不是排错）。
生成动作只读数据目录、只写目标 zip，不打网络。
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path

MAX_LOG_BYTES = 256 * 1024
MAX_LOG_FILES = 5
#: 字段名里出现这些词 → 值打码（大小写不敏感）
SENSITIVE_HINTS = ("key", "token", "secret", "password", "passwd", "cookie",
                   "authorization", "credential")
_URL_CREDS = re.compile(r"//[^/@\s]+@")


def scrub(value, *, hint: str = ""):
    """递归脱敏：字段名命中 SENSITIVE_HINTS 的值打码，URL 里的 `user:pass@` 抹掉。"""
    if isinstance(value, dict):
        return {str(k): scrub(v, hint=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, hint=hint) for v in value]
    if isinstance(value, str):
        text = _URL_CREDS.sub("//***@", value)
        if hint and any(word in hint.lower() for word in SENSITIVE_HINTS) and text.strip():
            return "***"
        return text
    return value


class DiagnosticsService:
    """收集 + 打包；界面（桥接）与命令行（tools/collect_diagnostics.py）共用。"""

    def __init__(self, *, library=None, plugins_service=None, sources=None,
                 root: Path | None = None, logger=None, version: str = "") -> None:
        self._library = library
        self._plugins = plugins_service
        self._sources = sources
        self._logger = logger
        self._version = version
        self._root = Path(root) if root else self._default_root()

    # ------------------------------------------------------------------ #
    def build(self, out_path: Path | str | None = None) -> dict:
        """生成诊断包；返回 {ok, path, bytes, entries, dir}。"""
        folder = "Aurora-diagnostics-" + time.strftime("%Y%m%d-%H%M%S")
        target = Path(out_path) if out_path else (self._root / "diagnostics" / f"{folder}.zip")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{folder}/README.txt", _readme_text())
                zf.writestr(f"{folder}/summary.json",
                            json.dumps(self.summary(), ensure_ascii=False, indent=2))
                zf.writestr(f"{folder}/settings.json",
                            json.dumps(self.settings_snapshot(), ensure_ascii=False, indent=2))
                for name, blob in self.log_blobs().items():
                    zf.writestr(f"{folder}/logs/{name}", blob)
        except Exception as exc:                            # noqa: BLE001
            if self._logger:
                self._logger(f"diagnostics failed: {exc}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "path": str(target)}
        entries = sorted(str(rel) for rel in _zip_names(target))
        return {"ok": True, "path": str(target), "dir": str(target.parent),
                "bytes": target.stat().st_size, "entries": entries}

    # ------------------------------------------------------------------ #
    def settings_snapshot(self) -> dict:
        settings = dict(getattr(self._library, "settings", None) or {})
        return scrub(settings)

    def summary(self) -> dict:
        from aurora.infra.store import migrations, paths

        library = self._library
        games = _call_list(library, "all")
        shelves = _call_list(library, "shelves")
        settings = dict(getattr(library, "settings", None) or {})
        out: dict = {
            "app": "Aurora",
            "version": self._version or "",
            "generated_at": int(time.time()),
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "machine": platform.machine(),
                "cpu_count": os.cpu_count(),
                "frozen": bool(getattr(sys, "frozen", False)),
            },
            "data": {
                "root": str(self._root),
                "games": len(games),
                "shelves": len(shelves),
                "settings_keys": len(settings),
                "disk_free_mb": _disk_free_mb(self._root),
            },
            "migration": self._migration_plan(paths, migrations),
            "plugins": self._plugin_rows(),
            "sources": self._source_rows(),
        }
        return scrub(out)

    def log_blobs(self) -> dict[str, str]:
        """日志尾部（名字 → 文本）；按修改时间取最近几个。"""
        candidates: list[Path] = []
        logs_dir = self._root / "logs"
        if logs_dir.is_dir():
            candidates += [p for p in logs_dir.glob("*.log") if p.is_file()]
        legacy = self._root / "aurora.log"
        if legacy.is_file():
            candidates.append(legacy)
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        blobs: dict[str, str] = {}
        for path in candidates[:MAX_LOG_FILES]:
            blobs[path.name] = _tail_text(path, MAX_LOG_BYTES)
        return blobs

    # ------------------------------------------------------------------ #
    def _migration_plan(self, paths, migrations) -> dict:
        try:
            layout = paths.default_layout()
            return migrations.plan(layout).as_dict()
        except Exception as exc:                            # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}

    def _plugin_rows(self) -> list[dict]:
        if self._plugins is None:
            return []
        try:
            return [status.as_dict() for status in self._plugins.statuses()]
        except Exception as exc:                            # noqa: BLE001
            return [{"error": f"{type(exc).__name__}: {exc}"}]

    def _source_rows(self) -> list[dict]:
        if self._sources is None:
            return []
        try:
            return list(self._sources.describe())
        except Exception as exc:                            # noqa: BLE001
            return [{"error": f"{type(exc).__name__}: {exc}"}]

    def _default_root(self) -> Path:
        try:
            from gl import config

            return Path(config.DATA_DIR)
        except Exception:                                   # noqa: BLE001
            return Path.cwd() / "data"


def _call_list(obj, name: str) -> list:
    fn = getattr(obj, name, None)
    if callable(fn):
        try:
            return list(fn() or [])
        except Exception:                                   # noqa: BLE001
            return []
    return list(getattr(obj, "games", None) or [])


def _disk_free_mb(path: Path) -> int:
    try:
        probe = path if path.exists() else path.parent
        return int(shutil.disk_usage(str(probe)).free / 1048576)
    except Exception:                                       # noqa: BLE001
        return -1


def _tail_text(path: Path, limit: int) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            data = handle.read()
        text = data.decode("utf-8", "replace")
        if size > limit:
            text = f"（只保留尾部 {limit // 1024} KB，原文 {size // 1024} KB）\n" + text
        return text
    except Exception as exc:                                # noqa: BLE001
        return f"（读不出来：{type(exc).__name__}: {exc}）"


def _zip_names(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    except Exception:                                       # noqa: BLE001
        return []


def _readme_text() -> str:
    return (
        "Aurora 诊断包\r\n"
        "================\r\n\r\n"
        "这个 zip 是为了排错用的，里面只有：\r\n"
        "  summary.json    版本 / 系统 / 数据目录计数 / 迁移计划 / 插件与资料源状态\r\n"
        "  settings.json   设置快照（API Key、token、密码类字段已打码，URL 里的账密已抹掉）\r\n"
        "  logs/           日志尾部（每个文件最多 256 KB）\r\n\r\n"
        "不包含：游戏可执行文件、素材原图、游戏库全文。\r\n"
        "如果还是担心，打开 zip 自己看一眼再发；日志里可能夹着你启动过的游戏名与路径。\r\n\r\n"
        "怎么把包发给维护者：把整个 zip 发给 Aurora 的 issue / 讨论区即可。\r\n"
    )
