"""诊断包（P7）：脱敏、内容清单与失败隔离。

用临时目录 + 桩对象跑，不碰真实数据目录，也不打网络。
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aurora.app.services.diagnostics import DiagnosticsService, scrub  # noqa: E402


class _Lib:
    def __init__(self, settings=None, games=None, shelves=None):
        self.settings = settings or {}
        self._games = list(games or [])
        self._shelves = list(shelves or [])

    def all(self):
        return [dict(g) for g in self._games]

    def shelves(self):
        return [dict(s) for s in self._shelves]


class _Plugins:
    class _Status:
        def __init__(self, pid, state="ok"):
            self._row = {"kind": "translators", "id": pid, "name": pid, "version": "1.0.0",
                         "path": f"C:/plugins/{pid}", "state": state, "detail": "",
                         "permissions": ["network"], "settings": [], "failures": 0}

        def as_dict(self):
            return dict(self._row)

    def statuses(self):
        return [self._Status("demo", "ok"), self._Status("old", "incompatible")]


class _Sources:
    def describe(self):
        return [{"id": "steam", "name": "Steam", "enabled": True}]


def test_scrub_masks_secrets_and_url_credentials():
    data = {
        "translate_api_key": "sk-secret",
        "proxy_url": "http://user:pw@127.0.0.1:7890",
        "nested": {"access_token": "abc", "custom": [{"apiKey": "k"}]},
        "plain": "keep me",
    }
    out = scrub(data)
    assert out["translate_api_key"] == "***"
    assert out["nested"]["access_token"] == "***"
    assert out["nested"]["custom"][0]["apiKey"] == "***"
    assert out["proxy_url"] == "http://***@127.0.0.1:7890"
    assert out["plain"] == "keep me"


def test_build_writes_zip_with_summary_and_redacted_settings(tmp_path):
    library = _Lib(settings={"translate_api_key": "sk-x", "translate_model": "deepseek-chat",
                             "proxy_url": "http://u:p@127.0.0.1:7890"},
                   games=[{"id": "g1"}, {"id": "g2"}],
                   shelves=[{"id": "s1", "name": "分类"}])
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "aurora.log").write_text("第一行\n第二行\n", encoding="utf-8")
    service = DiagnosticsService(library=library, plugins_service=_Plugins(),
                                 sources=_Sources(), root=tmp_path, version="1.0.0")
    out = tmp_path / "diag.zip"
    res = service.build(out_path=out)
    assert res["ok"] and Path(res["path"]).is_file()
    assert res["bytes"] > 0 and len(res["entries"]) >= 4

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        base = names[0].split("/")[0]
        assert f"{base}/README.txt" in names
        assert f"{base}/logs/aurora.log" in names
        summary = json.loads(zf.read(f"{base}/summary.json").decode("utf-8"))
        settings = json.loads(zf.read(f"{base}/settings.json").decode("utf-8"))
        readme = zf.read(f"{base}/README.txt").decode("utf-8")
    assert summary["app"] == "Aurora" and summary["version"] == "1.0.0"
    assert summary["data"]["games"] == 2 and summary["data"]["shelves"] == 1
    assert [p["id"] for p in summary["plugins"]] == ["demo", "old"]
    assert summary["sources"][0]["id"] == "steam"
    assert settings["translate_api_key"] == "***"
    assert settings["proxy_url"] == "http://***@127.0.0.1:7890"
    assert settings["translate_model"] == "deepseek-chat"      # 非敏感字段照常保留
    assert "不包含" in readme


def test_log_tail_is_truncated(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "aurora.log").write_text("x" * (300 * 1024), encoding="utf-8")
    service = DiagnosticsService(library=_Lib(), root=tmp_path)
    blob = service.log_blobs()["aurora.log"]
    assert "只保留尾部" in blob
    assert len(blob.encode("utf-8")) < 300 * 1024


def test_missing_optional_pieces_do_not_break(tmp_path):
    """没有插件服务 / 资料源 / 日志目录也要能出包（CLI 在干净 checkout 上跑）。"""
    service = DiagnosticsService(library=_Lib(), root=tmp_path)
    res = service.build()
    assert res["ok"]
    with zipfile.ZipFile(res["path"]) as zf:
        name = next(n for n in zf.namelist() if n.endswith("summary.json"))
        summary = json.loads(zf.read(name).decode("utf-8"))
    assert summary["plugins"] == [] and summary["sources"] == []
    assert summary["data"]["games"] == 0


def test_build_reports_error_when_target_is_a_directory(tmp_path):
    """目标路径不可写时不抛异常，返回 ok=False + 原因。"""
    blocker = tmp_path / "blocked.zip"
    blocker.mkdir()
    service = DiagnosticsService(library=_Lib(), root=tmp_path)
    res = service.build(out_path=blocker)
    assert res["ok"] is False and "error" in res
