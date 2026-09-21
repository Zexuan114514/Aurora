"""插件加载（P6.2，ADR-0009）：`data/plugins/<kind>/<id>/plugin.json` + 入口模块。

信任模型如实写在这里：**插件在宿主进程内、以用户权限运行，能读文件、能联网**，
宿主只保证「插件异常不会带崩宿主」，不保证「插件不做坏事」。

只做四件事：
  1. 发现：扫 `data/plugins/{sources,translators}/<id>/`
  2. 校验：manifest schema + `api_version` 门禁 + id 与目录名一致
  3. 加载：`importlib.util.spec_from_file_location`（**不改 `sys.path`**）→ 找入口类 → 注入 `HostContext`
  4. 状态：每个插件一条 `PluginStatus`（含失败原因），失败只影响它自己

调用侧用 `CallGuard` 包一层：连续 3 次失败自动禁用（状态改 `disabled`）。
"""
from __future__ import annotations

import importlib.util
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API_MAJOR, API_MINOR = 1, 0
HOST_VERSION = f"{API_MAJOR}.{API_MINOR}"
KINDS = ("sources", "translators")
_ID_RE = re.compile(r"^[a-z0-9_-]{3,32}$")
_STATE_OK = "ok"

__all__ = ["PluginStatus", "HostContext", "CallGuard", "discover", "load_all",
           "HOST_VERSION", "KINDS"]


@dataclass
class PluginStatus:
    """一个插件的加载结果（`state` 是界面要显示的那一列）。"""

    kind: str
    id: str
    name: str = ""
    version: str = ""
    path: str = ""
    state: str = _STATE_OK
    detail: str = ""
    permissions: tuple[str, ...] = ()
    settings_schema: list = field(default_factory=list)
    plugin: object | None = None
    failures: int = 0

    @property
    def ok(self) -> bool:
        return self.state == _STATE_OK

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "id": self.id, "name": self.name,
            "version": self.version, "path": self.path, "state": self.state,
            "detail": self.detail, "permissions": list(self.permissions),
            "settings": self.settings_schema, "failures": self.failures,
        }


@dataclass
class HostContext:
    """交给插件的宿主能力（设置、日志、HTTP、时钟）。"""

    plugin_id: str
    settings: dict = field(default_factory=dict)
    logger: object | None = None

    def get(self, key: str, default=None):
        return (self.settings or {}).get(key, default)

    def log(self, message: str) -> None:
        text = f"plugin[{self.plugin_id}] {message}"
        if callable(self.logger):
            self.logger(text)

    def http(self):
        """带宿主代理设置的 urllib opener（插件联网统一走它）。"""
        try:
            from aurora.infra import netproxy

            opener = getattr(netproxy, "opener", None)
            if callable(opener):
                return opener()
        except Exception:                                   # noqa: BLE001
            pass
        return urllib.request.build_opener()

    @staticmethod
    def now() -> float:
        return time.time()


class PluginDisabled(RuntimeError):
    """插件已因连续失败被禁用。"""


class CallGuard:
    """包住插件调用：异常只记一次并计数，连续 3 次把插件标成 disabled。"""

    def __init__(self, status: PluginStatus, limit: int = 3, logger=None) -> None:
        self.status = status
        self.limit = max(1, int(limit))
        self.logger = logger

    def call(self, fn, *args, **kwargs):
        if self.status.state == "disabled":
            raise PluginDisabled(f"{self.status.id} 已被禁用")
        try:
            result = fn(*args, **kwargs)
        except PluginDisabled:
            raise
        except Exception as exc:                            # noqa: BLE001
            self.status.failures += 1
            self.status.detail = f"调用失败（{type(exc).__name__}: {exc}）"
            if self.logger:
                self.logger(f"plugin[{self.status.id}] call failed: {exc}")
            if self.status.failures >= self.limit:
                self.status.state = "disabled"
                self.status.detail = f"连续 {self.status.failures} 次失败，已自动禁用"
            raise
        else:
            if self.status.failures:
                self.status.failures = 0
                self.status.detail = ""
            return result


def _check_api_version(value: str) -> str:
    text = str(value or "")
    if not re.fullmatch(r"\d+\.\d+", text):
        return f"api_version 要写成「主.次」：{text!r}"
    major, minor = (int(part) for part in text.split("."))
    if major != API_MAJOR:
        return f"插件 api_version {text} 与宿主 {HOST_VERSION} 主版本不一致"
    if minor > API_MINOR:
        return f"插件 api_version {text} 的次版本高于宿主 {HOST_VERSION}"
    return ""


def validate_manifest(data: dict, kind: str, directory: str) -> str:
    """校验 manifest；通过返回空串，否则返回人话原因。"""
    if not isinstance(data, dict):
        return "manifest 不是对象"
    error = _check_api_version(data.get("api_version"))
    if error:
        return error
    if str(data.get("kind") or "") != kind.rstrip("s"):
        return f"kind 必须是 {kind.rstrip('s')}（当前 {data.get('kind')!r}）"
    pid = str(data.get("id") or "")
    if not _ID_RE.fullmatch(pid):
        return f"id 非法（要求 [a-z0-9_-]{{3,32}}）：{pid!r}"
    if pid != directory:
        return f"目录名必须等于 id：目录 {directory!r} / id {pid!r}"
    for key, label in (("name", "显示名"), ("version", "版本"), ("entry", "入口文件")):
        if not str(data.get(key) or "").strip():
            return f"缺 {key}（{label}）"
    permissions = data.get("permissions")
    if permissions is not None and not isinstance(permissions, list):
        return "permissions 必须是数组（自述用途，不做强制拦截）"
    settings = data.get("settings")
    if settings is not None and not isinstance(settings, list):
        return "settings 必须是数组（每项 {key,label,type,default}）"
    return ""


def _find_plugin_class(module, class_name: str = ""):
    if class_name:
        found = getattr(module, class_name, None)
        return found
    for value in vars(module).values():
        if isinstance(value, type) and value.__module__ == module.__name__ and value.__name__ != "Plugin":
            return value
    return getattr(module, "Plugin", None)


def load_plugin(kind: str, directory: Path, *, logger=None) -> PluginStatus:
    """加载一个插件目录；任何失败都落成状态，不抛异常。"""
    pid = directory.name
    status = PluginStatus(kind=kind, id=pid, path=str(directory))
    manifest_path = directory / "plugin.json"
    if not manifest_path.is_file():
        status.state, status.detail = "manifest-error", "缺 plugin.json"
        return status
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:                                # noqa: BLE001
        status.state, status.detail = "manifest-error", f"读不出来：{exc}"
        return status

    status.name = str(data.get("name") or "")
    status.version = str(data.get("version") or "")
    status.permissions = tuple(data.get("permissions") or ())
    status.settings_schema = list(data.get("settings") or [])

    error = validate_manifest(data, kind, pid)
    if error:
        status.state = ("incompatible" if "api_version" in error else "manifest-error")
        status.detail = error
        return status

    entry = directory / str(data.get("entry") or "main.py")
    if not entry.is_file():
        status.state, status.detail = "load-error", f"入口文件不存在：{entry.name}"
        return status
    module_name = f"aurora_plugin_{kind.rstrip('s')}_{pid}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, entry)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)                     # 不碰 sys.path
    except Exception as exc:                                # noqa: BLE001
        status.state, status.detail = "load-error", f"{type(exc).__name__}: {exc}"
        return status

    cls = _find_plugin_class(module, str(data.get("class") or ""))
    if cls is None:
        status.state, status.detail = "init-error", "入口模块里找不到插件类"
        return status
    try:
        plugin = cls()
        host = HostContext(plugin_id=pid, settings={}, logger=logger)
        binder = getattr(plugin, "bind_host", None)
        if callable(binder):
            binder(host)
        plugin.host = host
    except Exception as exc:                                # noqa: BLE001
        status.state, status.detail = "init-error", f"{type(exc).__name__}: {exc}"
        return status
    status.plugin = plugin
    if logger:
        logger(f"plugin[{pid}] loaded from {directory}")
    return status


def discover(root: Path, *, logger=None) -> list[PluginStatus]:
    """扫一棵插件根目录（`<root>/<kind>/<id>/`），逐插件容错。"""
    out: list[PluginStatus] = []
    seen: set[tuple[str, str]] = set()
    for kind in KINDS:
        base = Path(root) / kind
        if not base.is_dir():
            continue
        for directory in sorted(p for p in base.iterdir() if p.is_dir()):
            status = load_plugin(kind, directory, logger=logger)
            key = (kind, status.id)
            if key in seen:
                status.state, status.detail = "duplicate", "同一个 id 出现了两次"
            seen.add(key)
            out.append(status)
    return out


def load_all(user_dir: Path | None = None, *, logger=None) -> list[PluginStatus]:
    """加载用户插件目录（默认 `<DATA_DIR>/plugins`）。"""
    if user_dir is None:
        try:
            from aurora.infra import config

            user_dir = Path(config.DATA_DIR) / "plugins"
        except Exception:                                   # noqa: BLE001
            return []
    return discover(Path(user_dir), logger=logger)
