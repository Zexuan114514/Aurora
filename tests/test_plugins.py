"""插件框架（P6.2，ADR-0009）：manifest 门禁、加载、状态、调用守卫与自动禁用。

用临时目录里的 fake 插件跑「发现 → 注册 → 调用 → 失败 → 禁用」这条主线，
不依赖任何真实插件，也不需要网络。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aurora.infra import plugins  # noqa: E402


def make_plugin(root: Path, kind: str, pid: str, *, manifest: dict | None = None,
                body: str = "class Plugin:\n    def search(self, query):\n        return []\n") -> Path:
    directory = root / kind / pid
    directory.mkdir(parents=True, exist_ok=True)
    data = {"api_version": plugins.HOST_VERSION, "kind": kind.rstrip("s"), "id": pid,
            "name": f"{pid} 插件", "version": "1.0.0", "entry": "main.py"}
    if manifest:
        data.update(manifest)
    (directory / "plugin.json").write_text(json.dumps(data, ensure_ascii=False),
                                           encoding="utf-8")
    (directory / "main.py").write_text(body, encoding="utf-8")
    return directory


def test_discover_loads_plugin_and_registers_status(tmp_path):
    make_plugin(tmp_path, "sources", "demo-source")
    statuses = plugins.discover(tmp_path)
    assert len(statuses) == 1
    status = statuses[0]
    assert status.ok and status.kind == "sources" and status.id == "demo-source"
    assert status.name == "demo-source 插件"
    assert status.plugin is not None and hasattr(status.plugin, "search")
    assert status.plugin.host.plugin_id == "demo-source"
    assert status.as_dict()["state"] == "ok"


def test_bind_host_receives_context(tmp_path):
    body = (
        "class Plugin:\n"
        "    def bind_host(self, host):\n"
        "        self.seen = host.get('token', 'default')\n"
    )
    make_plugin(tmp_path, "translators", "demo-trans", body=body)
    status = plugins.discover(tmp_path)[0]
    assert status.ok
    assert status.plugin.seen == "default"


@pytest.mark.parametrize("manifest,needle,state", [
    ({"api_version": "2.0"}, "主版本", "incompatible"),
    ({"api_version": "1.9"}, "次版本", "incompatible"),
    ({"api_version": "1"}, "主.次", "incompatible"),
    ({"kind": "translator"}, "kind 必须是 source", "manifest-error"),
    ({"id": "OK_ID"}, "id 非法", "manifest-error"),
    ({"name": ""}, "缺 name", "manifest-error"),
    ({"permissions": "network"}, "permissions 必须是数组", "manifest-error"),
])
def test_bad_manifests_are_rejected(tmp_path, manifest, needle, state):
    make_plugin(tmp_path, "sources", "bad-manifest", manifest=manifest)
    status = plugins.discover(tmp_path)[0]
    assert not status.ok
    assert status.state == state
    assert needle in status.detail


def test_directory_name_must_match_id(tmp_path):
    directory = make_plugin(tmp_path, "sources", "right-id")
    data = json.loads((directory / "plugin.json").read_text(encoding="utf-8"))
    data["id"] = "other-id"
    (directory / "plugin.json").write_text(json.dumps(data), encoding="utf-8")
    status = plugins.discover(tmp_path)[0]
    assert status.state == "manifest-error"
    assert "目录名必须等于 id" in status.detail


def test_entry_errors_are_isolated(tmp_path):
    make_plugin(tmp_path, "sources", "boom", body="raise RuntimeError('导入就炸')\n")
    make_plugin(tmp_path, "sources", "fine")
    statuses = {s.id: s for s in plugins.discover(tmp_path)}
    assert statuses["boom"].state == "load-error" and "导入就炸" in statuses["boom"].detail
    assert statuses["fine"].ok            # 坏插件不影响好插件


def test_missing_manifest_and_entry(tmp_path):
    (tmp_path / "sources" / "no-manifest").mkdir(parents=True)
    assert plugins.discover(tmp_path)[0].state == "manifest-error"

    directory = make_plugin(tmp_path, "sources", "no-entry")
    (directory / "main.py").unlink()
    statuses = [s for s in plugins.discover(tmp_path) if s.id == "no-entry"]
    assert statuses[0].state == "load-error"


def test_call_guard_disables_after_three_failures(tmp_path):
    make_plugin(tmp_path, "sources", "flaky", body=(
        "class Plugin:\n"
        "    def search(self, query):\n"
        "        raise ValueError('一直失败')\n"))
    status = plugins.discover(tmp_path)[0]
    guard = plugins.CallGuard(status, limit=3)
    for expected in range(1, 4):
        with pytest.raises(ValueError):
            guard.call(status.plugin.search, "x")
        assert status.failures == expected
    assert status.state == "disabled"
    assert "已自动禁用" in status.detail
    # 再调用直接拒绝，且计数不再变化
    with pytest.raises(plugins.PluginDisabled):
        guard.call(status.plugin.search, "x")
    assert status.failures == 3


def test_call_guard_resets_counter_on_success(tmp_path):
    body = (
        "class Plugin:\n"
        "    calls = 0\n"
        "    def search(self, query):\n"
        "        Plugin.calls += 1\n"
        "        if Plugin.calls == 1:\n"
        "            raise ValueError('就失败一次')\n"
        "        return ['ok']\n"
    )
    make_plugin(tmp_path, "sources", "flaky-once", body=body)
    status = plugins.discover(tmp_path)[0]
    guard = plugins.CallGuard(status, limit=3)
    with pytest.raises(ValueError):
        guard.call(status.plugin.search, "x")
    assert status.failures == 1
    assert guard.call(status.plugin.search, "x") == ["ok"]
    assert status.failures == 0 and status.ok


def test_load_all_defaults_to_data_dir(tmp_path, monkeypatch):
    from aurora.infra import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    make_plugin(tmp_path / "plugins", "sources", "from-data")
    statuses = plugins.load_all()
    assert [s.id for s in statuses] == ["from-data"]


def test_plugin_service_status_and_rescan(tmp_path):
    """插件服务（桥接层背后的那一层）：状态查询与重新扫描。"""
    from aurora.app.services.plugins import PluginsService

    service = PluginsService(tmp_path)
    first = service.list()
    assert first["ok"] and first["plugins"] == []
    assert first["dir"].endswith("plugins")
    make_plugin(tmp_path / "plugins", "translators", "fresh-one")
    again = service.rescan()
    assert [p["id"] for p in again["plugins"]] == ["fresh-one"]
    assert again["plugins"][0]["state"] == "ok"
    assert service.statuses()[0].plugin is not None


def test_bridge_mixin_forwards_to_plugin_service(tmp_path):
    """桥接层只做转发（分层守卫：bridge 不许 import infra）。"""
    from aurora.app.services.plugins import PluginsService
    from aurora.ui.bridge.settings import SettingsBridgeMixin

    class Dummy(SettingsBridgeMixin):
        pass

    dummy = Dummy()
    dummy._plugins_service = PluginsService(tmp_path)
    make_plugin(tmp_path / "plugins", "sources", "via-bridge")
    payload = dummy.list_plugins()
    assert payload["ok"] and [p["id"] for p in payload["plugins"]] == ["via-bridge"]
    assert dummy.rescan_plugins()["plugins"][0]["state"] == "ok"
