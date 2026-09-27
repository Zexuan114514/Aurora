"""「我的引擎规则包」导出（开源化 P1）：H-code 解析、指纹、规则包 schema、跳过隔离。

用临时目录 + 桩对象跑，不碰真实数据目录，也不打网络。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aurora.app.services.rule_export import RuleExportService  # noqa: E402
from aurora.domain import engine_rules  # noqa: E402
from aurora.infra import rules as rules_mod  # noqa: E402

BUILTIN = ROOT / "aurora" / "rules" / "engines" / "hooks.json"


class _Lib:
    def __init__(self, games):
        self._games = list(games)

    def all(self):
        return [dict(g) for g in self._games]


def test_parse_hook_code_roundtrip():
    parsed = engine_rules.parse_hook_code("HS65001#-6C@1B1F70:Amakano3.exe")
    assert parsed == {"mode": "S", "offset": -0x6C, "rva": 0x1B1F70,
                      "module": "Amakano3.exe", "codepage": 65001}
    assert engine_rules.parse_hook_code("HQ-4@A22E:AdvHD_crack.exe")["offset"] == -4
    assert engine_rules.parse_hook_code("HQ4@A22E")["codepage"] is None
    assert engine_rules.parse_hook_code("不是钩子码") is None
    rebuilt = engine_rules.build_hook_code(
        {"mode": parsed["mode"], "offset": parsed["offset"],
         "rva": parsed["rva"], "codepage": parsed["codepage"]},
        parsed["module"])
    assert rebuilt == "HS65001#-6C@1B1F70:Amakano3.exe"


def test_rule_id_matches_builtin_package():
    """id 生成规则归 domain 后，内置包里的 id 必须还能原样复算出来。"""
    package = json.loads(BUILTIN.read_text(encoding="utf-8"))
    for rule in package["rules"]:
        fp = rule["fingerprint"]
        assert rule["id"] == engine_rules.rule_id(fp["name"], rule["engine"], fp["size"])


def test_export_writes_valid_pack_and_markdown(tmp_path: Path):
    body = b"demo-exe-body"
    exe = tmp_path / "advhd_crack.exe"
    exe.write_bytes(body)
    games = [{"id": "g1", "name": "少女之剑与秘密的协奏曲", "exe": str(exe),
              "vntext_hook": "HQ-4@A22E:AdvHD_crack.exe"}]

    result = RuleExportService(library=_Lib(games), root=tmp_path / "data").build()

    assert result["ok"] and result["rules"] == 1 and result["games"] == 1
    package = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert package["schema"] == rules_mod.SCHEMA
    rule = package["rules"][0]
    assert rules_mod.validate_rule(rule) == ""
    assert rule["fingerprint"]["name"] == "advhd_crack.exe"
    assert rule["fingerprint"]["size"] == len(body)
    assert rule["fingerprint"]["crc32"].startswith("0x")
    assert rule["engine"] == "WillPlus"
    assert rule["hook_code"]["rva"] == "0xA22E"
    assert rule["hook_code"]["offset"] == -4
    text = Path(result["markdown"]).read_text(encoding="utf-8")
    assert "引擎实测规则投稿" in text
    assert "HQ-4@A22E:AdvHD_crack.exe" in text


def test_export_skips_broken_code_and_missing_exe(tmp_path: Path):
    (tmp_path / "x.exe").write_bytes(b"x")
    games = [
        {"id": "a", "name": "坏码", "exe": str(tmp_path / "x.exe"), "vntext_hook": "nonsense"},
        {"id": "b", "name": "exe 不在了", "exe": str(tmp_path / "missing.exe"),
         "vntext_hook": "HQ-4@A22E:x.exe"},
    ]

    result = RuleExportService(library=_Lib(games), root=tmp_path / "data").build()

    assert result["ok"] and result["rules"] == 0
    assert len(result["skipped"]) == 2
    assert json.loads(Path(result["path"]).read_text(encoding="utf-8"))["rules"] == []


def test_export_marks_rules_already_in_builtin_pack(tmp_path: Path, monkeypatch):
    """指纹命中内置包的条目要在说明里标注，免得贡献者白填一遍表单。"""
    import aurora.app.services.rule_export as rule_export_mod

    monkeypatch.setattr(rule_export_mod, "_fingerprint",
                        lambda _path: {"name": "advhd_crack.exe", "size": 1992192,
                                       "crc32": 0x52EA5D63})
    games = [{"id": "g1", "name": "少女之剑与秘密的协奏曲",
              "exe": str(tmp_path / "AdvHD_crack.exe"),
              "vntext_hook": "HQ-4@A22E:AdvHD_crack.exe"}]

    result = RuleExportService(library=_Lib(games), root=tmp_path / "data").build()

    rule = json.loads(Path(result["path"]).read_text(encoding="utf-8"))["rules"][0]
    assert rule["evidence"]["already_bundled"] is True
    assert "不用重复提交" in Path(result["markdown"]).read_text(encoding="utf-8")
