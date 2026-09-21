"""引擎规则包加载（P6，ADR-0008）。

两处来源，用户覆盖内置：
  * 内置：`aurora/rules/engines/*.json`（随程序分发，由 tools/export_engine_rules.py 导出）
  * 用户：`data/rules/engines/*.json`（贡献者只写 JSON，不用读核心代码）

同指纹（文件名 + 字节数 + CRC32 三元组全等）时用户规则优先，并记一条日志，方便排查
「为什么这条码和文档不一样」。非法规则只拒绝它自己，不影响其它规则与宿主启动。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCHEMA = "aurora.engine-rules/1"
_HEX = re.compile(r"^0x[0-9A-Fa-f]+$")
_MODES = set("SQVABWHM")
_PROFILE_KEYS = {"name_prefix", "collapse_doubling", "dedupe_window", "variant_settle",
                 "hook_hint"}


def bundled_dir() -> Path:
    """内置规则包目录（打包后指向 PyInstaller 的解包目录）。"""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "")) / "aurora" / "rules" / "engines"
    else:
        base = Path(__file__).resolve().parents[1] / "rules" / "engines"
    return base


def validate_rule(rule: dict) -> str:
    """校验单条规则；通过返回空串，否则返回人话原因。"""
    if not isinstance(rule, dict):
        return "规则不是对象"
    rid = str(rule.get("id") or "")
    if not re.fullmatch(r"[a-z0-9_-]{3,64}", rid):
        return f"id 非法：{rid!r}"
    fp = rule.get("fingerprint") or {}
    if not str(fp.get("name") or ""):
        return f"{rid}: 缺 fingerprint.name"
    try:
        if int(fp.get("size")) <= 0:
            raise ValueError
    except Exception:
        return f"{rid}: fingerprint.size 非法"
    if not _HEX.match(str(fp.get("crc32") or "")):
        return f"{rid}: fingerprint.crc32 要写成 0x…"
    hook = rule.get("hook_code") or {}
    if str(hook.get("mode") or "")[:1].upper() not in _MODES:
        return f"{rid}: hook_code.mode 非法"
    if not _HEX.match(str(hook.get("rva") or "")):
        return f"{rid}: hook_code.rva 必须是模块内 RVA（0x…），不能写绝对地址"
    try:
        int(hook.get("offset") or 0)
    except Exception:
        return f"{rid}: hook_code.offset 非法"
    profile = rule.get("profile") or {}
    unknown = sorted(set(profile) - _PROFILE_KEYS)
    if unknown:
        return f"{rid}: profile 里有白名单外的键：{', '.join(unknown)}"
    return ""


def load_packages(directories) -> tuple[list[dict], list[str]]:
    """读若干目录下的 *.json；返回 (规则列表, 问题列表)。"""
    rules: list[dict] = []
    problems: list[str] = []
    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:                       # noqa: BLE001
                problems.append(f"{path.name}: 读不出来（{exc}）")
                continue
            if data.get("schema") != SCHEMA:
                problems.append(f"{path.name}: schema 不是 {SCHEMA}")
                continue
            for rule in data.get("rules") or []:
                error = validate_rule(rule)
                if error:
                    problems.append(f"{path.name}: {error}")
                    continue
                rules.append(rule)
    return rules, problems


def load_engine_rules(user_dir: Path | None = None,
                      builtin_dir: Path | None = None) -> tuple[list[dict], list[str]]:
    """内置 → 用户 合并；同指纹时用户覆盖（并记日志）。返回 (规则, 问题)。"""
    if user_dir is None:
        try:
            from aurora.infra import config

            user_dir = Path(config.DATA_DIR) / "rules" / "engines"
        except Exception:                                  # noqa: BLE001
            user_dir = None
    builtin, problems = load_packages([builtin_dir or bundled_dir()])
    user, user_problems = load_packages([user_dir] if user_dir else [])
    problems += user_problems

    merged: dict[tuple, dict] = {_key(r): r for r in builtin}
    for rule in user:
        key = _key(rule)
        if key in merged:
            _log(f"engine rule override: {merged[key]['id']} → {rule['id']}")
        merged[key] = rule
    return list(merged.values()), problems


def _key(rule: dict) -> tuple:
    fp = rule["fingerprint"]
    return (str(fp["name"]).lower(), int(fp["size"]), int(str(fp["crc32"]), 16))


def to_hook_rows(rules) -> list[dict]:
    """规则包 → domain 那套内部行（match_willplus_hook / build_hook_code 用）。"""
    rows = []
    for rule in rules:
        fp, hook, evidence = rule["fingerprint"], rule["hook_code"], rule.get("evidence") or {}
        rows.append({
            "name": fp["name"],
            "size": int(fp["size"]),
            "crc32": int(str(fp["crc32"]), 16),
            "rva": int(str(hook["rva"]), 16),
            "offset": int(hook.get("offset") or 0),
            "mode": str(hook.get("mode") or "Q"),
            "codepage": hook.get("codepage"),
            "engine": rule.get("engine") or "",
            "rule_id": rule.get("id") or "",
            "game": evidence.get("game") or "",
            "note": evidence.get("note") or "",
        })
    return rows


def _log(message: str) -> None:
    try:
        from aurora.infra import config

        config.log(message)
    except Exception:                                      # noqa: BLE001
        pass
