"""引擎规则包（P6，ADR-0008）：schema 校验、用户覆盖、导出与常量一致、hook 码不变。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aurora.domain import engine_rules  # noqa: E402
from aurora.infra import rules as rules_mod  # noqa: E402

BUILTIN = ROOT / "aurora" / "rules" / "engines"


def _write(tmp_path: Path, rules: list[dict]) -> Path:
    target = tmp_path / "rules" / "engines"
    target.mkdir(parents=True, exist_ok=True)
    (target / "user.json").write_text(
        json.dumps({"schema": rules_mod.SCHEMA, "rules": rules}, ensure_ascii=False),
        encoding="utf-8")
    return target


def test_builtin_packages_pass_schema():
    loaded, problems = rules_mod.load_packages([BUILTIN])
    assert problems == []
    assert len(loaded) >= 2


def test_builtin_matches_domain_constant():
    """导出脚本的产物必须与 domain 常量一致（防两份真相）。"""
    sys.path.insert(0, str(ROOT / "tools"))
    import export_engine_rules                      # noqa: PLC0415

    package = export_engine_rules.build_package()
    on_disk = json.loads((BUILTIN / "hooks.json").read_text(encoding="utf-8"))
    assert package == on_disk


def test_hook_code_from_rule_package_is_unchanged():
    """规则包 → 内部行 → H-code，与老常量的结果逐字相同。"""
    loaded, _ = rules_mod.load_engine_rules(user_dir=None, builtin_dir=BUILTIN)
    rows = rules_mod.to_hook_rows(loaded)
    for row in rows:
        old = engine_rules.match_willplus_hook(row["name"], row["size"], row["crc32"])
        assert old is not None, f"{row['name']} 在内置常量里找不到"
        module = row["name"]
        assert (engine_rules.build_hook_code(row, module)
                == engine_rules.build_hook_code(old, module))


def test_user_rule_overrides_builtin(tmp_path):
    builtin_rows, _ = rules_mod.load_packages([BUILTIN])
    sample = dict(builtin_rows[0])
    sample["id"] = "user-override-" + sample["id"]
    sample["hook_code"] = dict(sample["hook_code"], offset=-8)
    user_dir = _write(tmp_path, [sample])
    merged, problems = rules_mod.load_engine_rules(user_dir=user_dir, builtin_dir=BUILTIN)
    assert problems == []
    picked = [r for r in merged if r["fingerprint"]["name"] == sample["fingerprint"]["name"]]
    assert len(picked) == 1
    assert picked[0]["id"] == sample["id"]
    assert picked[0]["hook_code"]["offset"] == -8


def test_invalid_rules_are_rejected_with_reason():
    cases = [
        ({"id": "x"}, "id 非法"),
        ({"id": "ok-id", "fingerprint": {"name": "a.exe", "size": 1, "crc32": "AAAA"}},
         "crc32"),
        ({"id": "ok-id", "fingerprint": {"name": "a.exe", "size": 1, "crc32": "0x1"},
          "hook_code": {"mode": "Q", "rva": "12345", "offset": 0}}, "RVA"),
        ({"id": "ok-id", "fingerprint": {"name": "a.exe", "size": 1, "crc32": "0x1"},
          "hook_code": {"mode": "Q", "rva": "0x1", "offset": 0},
          "profile": {"nope": 1}}, "白名单"),
    ]
    for rule, needle in cases:
        error = rules_mod.validate_rule(rule)
        assert error and needle in error, (rule, error)


def test_bad_schema_package_is_skipped(tmp_path):
    target = tmp_path / "rules" / "engines"
    target.mkdir(parents=True, exist_ok=True)
    (target / "bad.json").write_text('{"schema": "nope/1", "rules": []}', encoding="utf-8")
    loaded, problems = rules_mod.load_packages([target])
    assert loaded == []
    assert problems and "schema" in problems[0]


def test_vntext_uses_rule_package(monkeypatch, tmp_path):
    """端到端接线：vntext 的自动 hook 码走规则包（内置 + 用户覆盖）。"""
    from aurora.infra import config  # noqa: PLC0415
    from aurora.infra import vntext  # noqa: PLC0415

    exported, _ = rules_mod.load_packages([BUILTIN])
    target = exported[0]
    fp = target["fingerprint"]
    monkeypatch.setattr(vntext, "file_fingerprint",
                        lambda _exe: {"name": fp["name"], "size": fp["size"],
                                      "crc32": int(str(fp["crc32"]), 16)})
    # 用户规则目录 = <DATA_DIR>/rules/engines（config 在导入时就把 DATA_DIR 定下来了）
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("AURORA_DISABLE_AUTO_HOOK", "")
    vntext._AUTO_HOOK_ROWS = None            # 丢掉缓存，强制重读规则包
    try:
        code = vntext.willplus_hook_code(f"C:/games/{fp['name']}")
        assert code.endswith(f":{fp['name']}")
        assert f"@{int(str(target['hook_code']['rva']), 16):X}" in code

        # 用户规则同指纹覆盖：偏移改成 -8，自动带的码也要跟着变
        override = dict(target)
        override["hook_code"] = dict(target["hook_code"], offset=-8)
        _write(tmp_path, [override])
        vntext._AUTO_HOOK_ROWS = None
        code2 = vntext.willplus_hook_code(f"C:/games/{fp['name']}")
        assert code2 != code
        assert "-8@" in code2
    finally:
        vntext._AUTO_HOOK_ROWS = None
