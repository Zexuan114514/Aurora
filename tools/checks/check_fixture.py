"""夹具守卫：去敏库夹具的形状与无泄露断言（P2 迁移测试的输入）。"""
from __future__ import annotations

import re
import sys

from common import ROOT, Result, load_json, main

FIXTURE = "tests/fixtures/library-v1.sanitized.json"
MANIFEST = "tests/fixtures/fixture-manifest.json"

FORBIDDEN_PATTERNS = (
    (r"C:\\Users", "绝对用户目录"),
    (r"HuHu1|Zexuan", "用户名 / 账号名"),
    (r"steampowered|cloudflare|bgm\.tv|vndb\.org", "真实商店或图床域名"),
    (r'"translate_api_key"\s*:\s*"[^"]+"', "非空 API Key"),
    (r"sk-[A-Za-z0-9]{8,}", "疑似密钥串"),
)


def check() -> Result:
    result = Result("去敏库夹具")
    fixture_path = ROOT / FIXTURE
    if not fixture_path.exists():
        result.fail(f"缺少夹具文件：{FIXTURE}")
        return result

    fixture = load_json(FIXTURE)
    manifest = load_json(MANIFEST)
    counts = manifest["counts"]
    games = fixture.get("games") or []

    if not isinstance(games, list) or not games:
        result.fail("夹具里没有 games 数组")
        return result

    if len(games) != counts["games"]:
        result.fail(f"游戏数不一致：夹具 {len(games)} / 清单 {counts['games']}")
    if len(fixture.get("settings") or {}) != counts["settings_keys"]:
        result.fail(f"设置项数不一致：{len(fixture.get('settings') or {})} / {counts['settings_keys']}")
    if len(fixture.get("bookshelves") or []) != counts["bookshelves"]:
        result.fail("分类书架数量与清单不一致")

    union = set().union(*[set(g) for g in games])
    expected_union = set(counts["game_field_union"])
    if union != expected_union:
        result.fail(f"字段并集与清单不一致：多 {sorted(union - expected_union)}，"
                    f"少 {sorted(expected_union - union)}")
    per_game = sorted({len(g) for g in games})
    if per_game != sorted(counts["per_game_field_counts"]):
        result.fail(f"每游戏字段数变化：{per_game} / 清单 {counts['per_game_field_counts']}")

    sessions = sum(len(g.get("sessions") or []) for g in games)
    if sessions != counts["session_records"]:
        result.fail(f"会话记录数变化：{sessions} / 清单 {counts['session_records']}")

    ids = [str(g.get("id") or "") for g in games]
    if any(not i for i in ids):
        result.fail("存在没有 id 的游戏记录")
    if len(set(ids)) != len(ids):
        result.fail("游戏 id 有重复")
    for game in games:
        if not str(game.get("name") or ""):
            result.fail(f"{game.get('id')} 缺少 name（去敏后不应为空）")
        exe = str(game.get("exe") or "")
        if exe and not re.fullmatch(r"C:\\Games\\Sample\d{2}\\game\.exe", exe):
            result.fail(f"{game.get('id')} 的 exe 路径不符合去敏规则：{exe}")

    if str((fixture.get("settings") or {}).get("translate_api_key") or ""):
        result.fail("settings.translate_api_key 未清空")

    blob = fixture_path.read_text(encoding="utf-8")
    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, blob, re.I):
            result.fail(f"夹具里出现敏感内容（{label}）：/{pattern}/")

    live = ROOT / "data" / "library.json"
    if live.exists():
        live_data = load_json("data/library.json")
        live_union = set().union(*[set(g) for g in live_data["games"]])
        extra = sorted(live_union - union)
        if extra:
            result.warn(f"本机实时库比夹具多了字段（夹具需要重新生成）：{extra}")
        result.note(f"本机实时库：{len(live_data['games'])} 游戏 / {len(live_union)} 字段（仅作对比，不参与判定）")

    result.note(f"夹具 {len(games)} 游戏 / {len(union)} 字段 / {sessions} 会话 / "
                f"{counts['settings_keys']} 设置项，反查无泄露")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
