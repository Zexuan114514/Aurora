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
    dummy._sources = type("S", (), {"set_plugin_statuses": lambda self, rows: None})()
    make_plugin(tmp_path / "plugins", "sources", "via-bridge")
    payload = dummy.list_plugins()
    assert payload["ok"] and [p["id"] for p in payload["plugins"]] == ["via-bridge"]
    assert dummy.rescan_plugins()["plugins"][0]["state"] == "ok"


def test_source_plugin_becomes_host_source(tmp_path):
    """插件资料源真的接进 SourceManager：能搜、能拉详情、状态可查。"""
    from gl.sources.manager import SourceManager

    body = (
        "class Plugin:\n"
        "    kind = 'api'\n"
        "    homepage = 'https://example.com'\n"
        "    supports_lang = True\n"
        "    def search(self, query, lang='schinese'):\n"
        "        return [{'source_id': 'g1', 'name': '插件搜到的游戏', 'score': 0.9}]\n"
        "    def fetch(self, candidate, lang='schinese'):\n"
        "        return {'description': '来自插件的简介', 'developers': ['某社']}\n"
    )
    make_plugin(tmp_path, "sources", "plug-src", body=body)
    statuses = plugins.discover(tmp_path)

    class _Lib:
        settings = {}

    manager = SourceManager(_Lib())
    manager.set_plugin_statuses(statuses)
    sources = [s for s in manager.sources() if s.id == "plug-src"]
    assert len(sources) == 1 and sources[0].kind == "api"

    found = sources[0].search(["某游戏"])
    assert [c.source_id for c in found] == ["g1"]
    assert found[0].source == "plug-src"          # source 自动补成插件 id
    detail = sources[0].fetch(found[0])
    assert detail is not None and detail.description == "来自插件的简介"
    assert detail.source == "plug-src" and detail.developers == ["某社"]
    assert any(row.get("plugin") for row in manager.describe())

    # 加载失败的插件不会变成资料源
    make_plugin(tmp_path, "sources", "plug-bad", body="raise RuntimeError('炸')\n")
    manager.set_plugin_statuses(plugins.discover(tmp_path))
    assert all(s.id != "plug-bad" for s in manager.sources())


# --------------------------------------------------------------------------- #
# P6.4 翻译引擎插件
# --------------------------------------------------------------------------- #
def _registry(tmp_path):
    """`PluginsService(data_dir)` 自己拼 `data_dir/plugins`，所以插件要建在 plugins 子目录下。"""
    from aurora.app.services.plugins import PluginsService
    from aurora.app.services.translators import TranslatorRegistry

    return TranslatorRegistry(PluginsService(tmp_path))


def _plug_root(tmp_path) -> Path:
    root = tmp_path / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_translator_plugin_becomes_host_engine(tmp_path):
    """插件翻译引擎的适配：入参归一、流式回调透传、provider 带 plugin: 前缀。"""
    body = (
        "class Plugin:\n"
        "    requires_key = True\n"
        "    supports_stream = True\n"
        "    def translate(self, text, *, context, target, glossary, on_delta):\n"
        "        on_delta('【流式】')\n"
        "        return {'text': '【插件】' + text, 'provider': 'demo'}\n"
    )
    make_plugin(_plug_root(tmp_path), "translators", "plug-trans", body=body)
    adapter = _registry(tmp_path).get("plug-trans")
    assert adapter is not None and adapter.available()
    assert adapter.provider == "plugin:plug-trans"
    assert adapter.requires_key and adapter.supports_stream

    seen: list[str] = []
    out = adapter.translate("こんにちは", context=["上文"], glossary={"私": "我"},
                            target="zh-CN", on_delta=seen.append)
    assert out == "【插件】こんにちは"
    assert seen == ["【流式】"]

    # 插件只给整段、不吐 delta 时，宿主补一段流式回执
    make_plugin(_plug_root(tmp_path), "translators", "whole-only", body=(
        "class Plugin:\n"
        "    def translate(self, text, **kw):\n"
        "        return '【整段】' + text\n"))
    adapter2 = _registry(tmp_path).get("whole-only")
    got: list[str] = []
    assert adapter2.translate("テスト", on_delta=got.append) == "【整段】テスト"
    assert got == ["【整段】テスト"]


def test_description_translation_uses_plugin_engine(tmp_path):
    """简介链路：`translate_provider = plugin:<id>` 时真的走插件（缓存归宿主）。"""
    from gl import translate

    make_plugin(_plug_root(tmp_path), "translators", "desk-trans", body=(
        "class Plugin:\n"
        "    def translate(self, text, *, context, target, glossary, on_delta):\n"
        "        return {'text': '【简介】' + text[:6]}\n"))
    service = _translation_service(tmp_path)
    mode = "plugin:desk-trans"
    res = translate.translate_text(
        "The story follows a young swordsman.", settings={"translate_provider": mode},
        plugin_translate=service._plugin_engine(mode))
    assert res["changed"] is True
    assert res["provider"] == mode and res["text"] == "【简介】The st"

    # 已经中文的文本不进翻译
    skip = translate.translate_text("中文简介", settings={"translate_provider": mode},
                                    plugin_translate=service._plugin_engine(mode))
    assert skip["changed"] is False


def test_plugin_engine_missing_and_failing(tmp_path):
    """插件不可用 / 插件失败：保持原文、provider 是 plugin:<id>，并给出 error。"""
    from gl import translate

    service = _translation_service(tmp_path)          # 目录里没有任何插件
    mode = "plugin:gone"
    res = translate.translate_text("The story follows a young swordsman.",
                                   settings={"translate_provider": mode},
                                   plugin_translate=service._plugin_engine(mode))
    assert res["changed"] is False and res["provider"] == mode
    assert res["error"] == "plugin-unavailable"

    make_plugin(_plug_root(tmp_path), "translators", "boom-trans", body=(
        "class Plugin:\n"
        "    def translate(self, text, **kw):\n"
        "        raise RuntimeError('引擎炸了')\n"))
    service = _translation_service(tmp_path)
    mode = "plugin:boom-trans"
    engine = service._plugin_engine(mode)
    for _ in range(3):
        res = translate.translate_text("The story follows a young swordsman.",
                                       settings={"translate_provider": mode},
                                       plugin_translate=engine)
        assert res["changed"] is False and res["error"] == "plugin-failed"
    status = [s for s in service.plugins_service.statuses() if s.id == "boom-trans"][0]
    assert status.state == "disabled" and "已自动禁用" in status.detail
    # 禁用后再取：拿不到引擎 → 状态变成「不可用」，界面据此提示
    assert service._plugin_engine(mode) is None


def _translation_service(tmp_path):
    """只借 TranslationService 的 provider 选择逻辑（不拉整棵 Api）。"""
    from aurora.app.services.plugins import PluginsService
    from aurora.app.services.translation import TranslationService
    from aurora.app.services.translators import TranslatorRegistry

    class _Lib:
        settings: dict = {}

    plugins_service = PluginsService(tmp_path)
    registry = TranslatorRegistry(plugins_service)
    service = TranslationService(_Lib(), None, None, None, plugin_getter=registry.get)
    service.plugins_service = plugins_service      # 测试用把手
    return service


def test_test_provider_reports_plugin(tmp_path):
    """设置页「测试」按钮：选了插件就用插件测。"""
    from gl import translate

    make_plugin(_plug_root(tmp_path), "translators", "probe-trans", body=(
        "class Plugin:\n"
        "    def translate(self, text, **kw):\n"
        "        return '【测试】' + text[:4]\n"))
    service = _translation_service(tmp_path)
    mode = "plugin:probe-trans"
    good = translate.test_provider({"translate_provider": mode},
                                   plugin_translate=service._plugin_engine(mode))
    assert good["ok"] and good["provider"] == mode
    bad = translate.test_provider({"translate_provider": "plugin:nope"})
    assert bad["ok"] is False and "不可用" in bad["error"]


def test_line_translator_prefers_plugin_engine(tmp_path, monkeypatch):
    """游戏内逐句链路：选了插件引擎就先走插件（带上下文 / 术语表 / 流式回调）。"""
    from aurora.infra import linetrans

    make_plugin(_plug_root(tmp_path), "translators", "line-trans", body=(
        "class Plugin:\n"
        "    def translate(self, text, *, context, target, glossary, on_delta):\n"
        "        on_delta('【流】')\n"
        "        return {'text': '【插件】' + text}\n"))
    monkeypatch.setattr(linetrans.config, "CACHE_DIR", tmp_path / "cache")
    cfg = {"translate_provider": "plugin:line-trans", "translate_target": "zh-CN"}
    translator = linetrans.LineTranslator(settings_getter=lambda: cfg, on_event=None,
                                          plugin_getter=_registry(tmp_path).get)
    translator._run({"text": "彼女は静かに微笑んだ。", "game_id": "", "source": "test",
                     "token": 1})
    rows = translator.history()
    assert rows and rows[-1]["provider"] == "plugin:line-trans"
    assert rows[-1]["translation"] == "【插件】彼女は静かに微笑んだ。"


def test_line_translator_falls_back_when_plugin_fails(tmp_path, monkeypatch):
    """插件没给出结果：落回兜底链，并把「兜底来自插件」记进历史（界面据此提示）。"""
    from aurora.infra import linetrans
    from gl import translate

    make_plugin(_plug_root(tmp_path), "translators", "dead-trans", body=(
        "class Plugin:\n"
        "    def translate(self, text, **kw):\n"
        "        raise RuntimeError('插件挂了')\n"))
    monkeypatch.setattr(linetrans.config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(translate, "free_translate", lambda text, **kw: "【兜底】" + text)
    cfg = {"translate_provider": "plugin:dead-trans", "translate_target": "zh-CN"}
    translator = linetrans.LineTranslator(settings_getter=lambda: cfg, on_event=None,
                                          plugin_getter=_registry(tmp_path).get)
    translator._run({"text": "テスト台詞", "game_id": "", "source": "test", "token": 1})
    row = translator.history()[-1]
    assert row["provider"] == "free" and row["fallback_from"] == "plugin:dead-trans"
    assert row["translation"] == "【兜底】テスト台詞"
