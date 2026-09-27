"""导出「我的引擎规则包」（开源化 P1）：本机实测的 hook 码 → 可直接提交的规则包。

产物（默认写到 `<数据目录>/rules/export/`）：

    Aurora-engine-rules-<时间戳>.json   规则包本体（schema 与内置包一致，维护者可原样合并）
    Aurora-engine-rules-<时间戳>.md     按 issue 表单字段排好的说明，直接贴进 issue

数据来源（只读）：
  * 游戏库里每款游戏的实测 hook 码（`vntext_hook`，由「钩子查找器」通过后保存）
  * 用户自己放在 `data/rules/engines/*.json` 里的规则包

为了写指纹（文件名 + 字节数 + CRC32）会读一次游戏 exe；读不出来的条目跳过并列进 `skipped`。
生成动作只读数据目录与 exe、只写目标文件，不打网络。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from aurora.domain import engine_rules

SCHEMA = "aurora.engine-rules/1"


def _fingerprint(path: str) -> dict:
    """exe 的（文件名, 字节数, CRC32）——实现归 infra，跟自动带码用的是同一份。"""
    from aurora.infra.vntext import file_fingerprint

    return file_fingerprint(path)


def _guess_engine(name: str, module: str) -> str:
    """按 exe / 模块名猜引擎（猜不到留空，作者在 issue 里补）。"""
    text = f"{name} {module}".lower()
    for engine, hints in engine_rules.ENGINE_SIGNATURES:
        if any(hint in text for hint in hints):
            return engine
    return ""


def _load_user_packs(user_dir: Path) -> tuple[list[dict], list[str]]:
    from aurora.infra import rules as rules_mod

    return rules_mod.load_packages([user_dir])


def _key(rule: dict) -> tuple:
    fp = rule["fingerprint"]
    return (str(fp["name"]).lower(), int(fp["size"]), int(str(fp["crc32"]), 16))


def render_markdown(result: dict, stamp: str) -> str:
    """把导出的规则排成「照着 issue 表单抄一遍」的投稿说明。"""
    lines = [
        "# 引擎实测规则投稿（Aurora 导出）",
        "",
        f"导出时间：{stamp}",
        f"规则条数：{len(result['rules'])}",
        "",
        "怎么用：Issues → New issue → 「引擎实测规则」，把下面每段填进表单；",
        "同目录的 `Aurora-engine-rules-*.json` 是规则包本体，直接贴进表单的「规则包」一栏（或当附件）。",
        "",
    ]
    for index, rule in enumerate(result["rules"], 1):
        fp, hook, evidence = rule["fingerprint"], rule["hook_code"], rule["evidence"]
        code = engine_rules.build_hook_code(
            {"mode": hook["mode"], "offset": hook["offset"], "rva": int(str(hook["rva"]), 16),
             "codepage": hook.get("codepage")},
            hook.get("module") or fp["name"])
        note = evidence.get("note") or "—"
        if evidence.get("already_bundled"):
            note += "（指纹已在**内置规则包**里，不用重复提交）"
        lines += [
            f"## {index}. {evidence.get('game') or fp['name']}",
            f"- 引擎：{rule['engine']}",
            f"- exe 文件名：{fp['name']}",
            f"- 字节数：{fp['size']}",
            f"- CRC32：{fp['crc32']}",
            f"- H-code：{code}",
            "- 原文样例：（补一句游戏里的原文，便于核对编码与断句）",
            "- 是否转区：未填（是 / 否）",
            "- 是否缺字：未填（有缺字 / 没有）",
            f"- 备注：{note}",
            "",
        ]
    if result["skipped"]:
        lines += ["## 没能自动整理的部分", ""]
        for row in result["skipped"]:
            lines.append(f"- {row['game'] or '（无标题）'}：{row['reason']}"
                         f"（H-code: {row.get('hook_code') or '—'}）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class RuleExportService:
    """收集 + 打包；界面（设置 → 关于）与命令行共用。"""

    def __init__(self, *, library=None, root: Path | None = None, logger=None) -> None:
        self._library = library
        self._logger = logger
        self._root = Path(root) if root else Path.cwd() / "data"

    # ------------------------------------------------------------------ #
    def build(self, out_dir: Path | str | None = None) -> dict:
        """生成规则包；返回 {ok, path, markdown, bytes, rules, games, skipped}。"""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = Path(out_dir) if out_dir else (self._root / "rules" / "export")
        collected = self.collect()
        target = folder / f"Aurora-engine-rules-{stamp}.json"
        markdown = folder / f"Aurora-engine-rules-{stamp}.md"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            package = {"schema": SCHEMA, "rules": collected["rules"]}
            target.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
            markdown.write_text(render_markdown(collected, stamp),
                                encoding="utf-8", newline="\n")
        except Exception as exc:                            # noqa: BLE001
            if self._logger:
                self._logger(f"engine rules export failed: {exc}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "path": str(target)}
        if self._logger:
            self._logger(f"engine rules exported: {len(collected['rules'])} rules -> {target}")
        return {"ok": True, "path": str(target), "markdown": str(markdown),
                "bytes": target.stat().st_size, "rules": len(collected["rules"]),
                "games": collected["games"], "skipped": collected["skipped"]}

    # ------------------------------------------------------------------ #
    def collect(self) -> dict:
        """本机实测码 + 用户规则包 → (规则, 跳过原因)。"""
        rules: list[dict] = []
        skipped: list[dict] = []
        seen: set[tuple] = set()
        games = 0
        for game in self._games():
            code = str(game.get("vntext_hook") or "").strip()
            if not code:
                continue
            title = str(game.get("name") or "")
            rule = self._rule_from_game(game, code)
            if rule is None:
                skipped.append({"game": title, "hook_code": code,
                                "reason": "H-code 解析不了（请在 issue 里附上原文）"})
                continue
            key = _key(rule)
            if key in seen:
                continue
            seen.add(key)
            rules.append(rule)
            games += 1

        user_dir = self._root / "rules" / "engines"
        packs, problems = _load_user_packs(user_dir)
        for problem in problems:
            skipped.append({"game": "data/rules/engines", "hook_code": "",
                            "reason": f"规则包有问题：{problem}"})
        for rule in packs:
            key = _key(rule)
            if key in seen:
                continue
            seen.add(key)
            rules.append(rule)

        bundled = self._bundled_keys()
        for rule in rules:
            if _key(rule) in bundled:
                rule["evidence"]["already_bundled"] = True
        return {"rules": rules, "games": games, "skipped": skipped}

    # ------------------------------------------------------------------ #
    def _bundled_keys(self) -> set[tuple]:
        """内置规则包的指纹集合：用来在导出的说明里标注「这条不用再提交」。"""
        from aurora.infra import rules as rules_mod

        try:
            loaded, _problems = rules_mod.load_packages([rules_mod.bundled_dir()])
            return {_key(rule) for rule in loaded}
        except Exception as exc:                            # noqa: BLE001
            if self._logger:
                self._logger(f"engine rules export: bundled pack read failed: {exc}")
            return set()

    def _games(self) -> list[dict]:
        if self._library is None:
            return []
        try:
            return [dict(row) for row in (self._library.all() or [])]
        except Exception as exc:                            # noqa: BLE001
            if self._logger:
                self._logger(f"engine rules export: library read failed: {exc}")
            return []

    def _rule_from_game(self, game: dict, code: str) -> dict | None:
        parsed = engine_rules.parse_hook_code(code)
        if not parsed:
            return None
        exe = str(game.get("exe") or "")
        fp = self._safe_fingerprint(exe) if exe else {}
        if not fp:
            return None
        engine = _guess_engine(fp["name"], str(parsed.get("module") or ""))
        profile = engine_rules.profile_for(engine) if engine in engine_rules.ENGINE_PROFILES else {}
        codepage = parsed.get("codepage")
        rule = {
            "id": engine_rules.rule_id(fp["name"], engine or "unknown", fp["size"]),
            "fingerprint": {"name": fp["name"], "size": int(fp["size"]),
                            "crc32": f"0x{int(fp['crc32']):08X}"},
            "engine": engine or "unknown",
            "hook_code": {
                "mode": parsed["mode"],
                "offset": int(parsed["offset"]),
                "rva": f"0x{int(parsed['rva']):X}",
                "module": str(parsed.get("module") or fp["name"]),
                "codepage": int(codepage) if codepage else None,
            },
            "text": {"encoding": "utf-8" if int(codepage or 0) == 65001 else "utf-16",
                     "codepage": int(codepage) if codepage else None},
            "profile": profile,
            "evidence": {
                "date": time.strftime("%Y-%m-%d"),
                "game": str(game.get("name") or ""),
                "sample": "",
                "note": "Aurora 钩子查找器在本机实测保存",
            },
        }
        return rule if self._valid(rule) else None

    def _safe_fingerprint(self, exe: str) -> dict:
        try:
            return _fingerprint(exe)
        except Exception as exc:                            # noqa: BLE001
            if self._logger:
                self._logger(f"engine rules export: fingerprint failed for {exe}: {exc}")
            return {}

    @staticmethod
    def _valid(rule: dict) -> bool:
        from aurora.infra import rules as rules_mod

        return not rules_mod.validate_rule(rule)
