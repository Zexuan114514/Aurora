"""数据目录与状态文件的唯一解析点（P2）。

此前路径散落在 `gl/config.py` 的 import 期全局量里；现在统一由这里算出来，
`gl/config.py` 只是把它们暴露成同名常量（兼容老调用点）。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Aurora"
APP_TITLE = "Aurora 游戏启动器"
APP_ID = "aurora-launcher"
VERSION = "1.0.0"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """程序所在目录：源码运行是项目根目录，打包后是 exe 所在目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def resolve_data_dir(*, env: dict | None = None, program_dir: Path | None = None) -> Path:
    """解析顺序：AURORA_DATA → 程序目录 data/（可写）→ %LOCALAPPDATA%\\aurora-launcher。"""
    env = os.environ if env is None else env
    override = str(env.get("AURORA_DATA") or "").strip()
    if override:
        return Path(override).expanduser().resolve()

    root = Path(program_dir) if program_dir is not None else app_dir()
    candidate = root / "data"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except Exception:
        base = env.get("LOCALAPPDATA") or env.get("APPDATA") or str(Path.home())
        return Path(base) / APP_ID


@dataclass(frozen=True)
class Layout:
    """数据目录的完整布局（纯数据，不创建任何目录）。"""

    root: Path

    # ---- v2 状态 ----
    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def backup(self) -> Path:
        return self.state / "backup"

    @property
    def settings_file(self) -> Path:
        return self.state / "settings.json"

    @property
    def library_file(self) -> Path:
        return self.state / "library.json"

    @property
    def sessions_file(self) -> Path:
        return self.state / "sessions.jsonl"

    # ---- v1 遗留（迁移输入） ----
    @property
    def legacy_library(self) -> Path:
        return self.root / "library.json"

    @property
    def legacy_glossary(self) -> Path:
        return self.root / "glossary.json"

    # ---- 其它 ----
    @property
    def vntext(self) -> Path:
        return self.root / "vntext"

    @property
    def glossary_file(self) -> Path:
        return self.vntext / "glossary.json"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def log_file(self) -> Path:
        return self.logs / "aurora.log"

    @property
    def webview(self) -> Path:
        return self.root / "webview"

    @property
    def downloads(self) -> Path:
        return self.root / "downloads"

    # ---- 素材（P5 资产服务化之前仍在原位） ----
    @property
    def covers(self) -> Path:
        return self.root / "covers"

    @property
    def backgrounds(self) -> Path:
        return self.root / "backgrounds"

    @property
    def icons(self) -> Path:
        return self.root / "icons"

    def writable_dirs(self) -> tuple[Path, ...]:
        return (self.root, self.state, self.backup, self.vntext, self.cache,
                self.logs, self.webview, self.downloads, self.covers,
                self.backgrounds, self.icons)


def layout_for(root: Path | str) -> Layout:
    """显式布局（测试、迁移工具用）。"""
    return Layout(Path(root))


_DEFAULT: Layout | None = None


def default_layout() -> Layout:
    """进程级默认布局（只解析一次，避免每次调用都做写探测）。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Layout(resolve_data_dir())
    return _DEFAULT


def ensure_dirs(target: Layout) -> None:
    """创建所有需要的目录；只读介质下静默跳过（调用方决定降级）。"""
    for folder in target.writable_dirs():
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
