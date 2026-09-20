"""P2 验收：v1→v2 迁移、单写者去抖、会话追加、损坏恢复、导出脱敏与回滚。

所有用例都在临时目录里跑，绝不碰真实 data/。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.infra.store import migrations  # noqa: E402
from aurora.infra.store.atomic import checksum, read_json, read_jsonl  # noqa: E402
from aurora.infra.store.paths import layout_for  # noqa: E402
from aurora.infra.store.state import StateStore  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "library-v1.sanitized.json"


def make_v1(root: pathlib.Path) -> dict:
    """把去敏夹具摆成 v1 目录（data/library.json）。"""
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURE, root / "library.json")
    return json.loads((root / "library.json").read_text(encoding="utf-8"))


def open_store(root: pathlib.Path, **kwargs) -> tuple[StateStore, dict]:
    store = StateStore(layout_for(root), autostart=False, **kwargs)
    report = store.load()
    return store, report


def test_migration_preserves_every_field(tmp_path: pathlib.Path) -> None:
    raw = make_v1(tmp_path)
    store, report = open_store(tmp_path)

    assert report["layout"] == "migrated"
    assert (tmp_path / "state" / "settings.json").exists()
    assert (tmp_path / "state" / "library.json").exists()
    assert (tmp_path / "state" / "sessions.jsonl").exists()

    assert len(store.games) == len(raw["games"])
    assert len(store.shelves) == len(raw.get("bookshelves") or [])
    assert len(store.settings) == len(raw.get("settings") or {})

    # 逐游戏逐字段全等（这是「迁移不丢数据」的硬断言）
    for before, after in zip(raw["games"], store.games):
        assert set(before) == set(after), "字段集合被改变"
        for key, value in before.items():
            assert after[key] == value, f"字段 {key} 在迁移后变了"

    # 设置内容逐项相等
    for key, value in (raw.get("settings") or {}).items():
        assert store.settings[key] == value

    # 会话摊平：123 条历史 + 聚合值保持不变
    rows = read_jsonl(tmp_path / "state" / "sessions.jsonl")
    expected_sessions = sum(len(g.get("sessions") or []) for g in raw["games"])
    assert len(rows) == expected_sessions == 123
    assert all(row["source"] == "migrated-v1" for row in rows)
    assert sum(row["seconds"] for row in rows) == sum(
        s["seconds"] for g in raw["games"] for s in (g.get("sessions") or []))

    # 备份 + v1 文件搬走（不留两份真相）
    backups = list((tmp_path / "state" / "backup").glob("library-v1-*.json"))
    assert backups, "迁移必须留下备份"
    assert checksum(tmp_path / "state" / "backup" / backups[0].name) == checksum(FIXTURE)
    assert not (tmp_path / "library.json").exists()


def test_dry_run_writes_nothing(tmp_path: pathlib.Path) -> None:
    raw = make_v1(tmp_path)
    plan = migrations.plan(layout_for(tmp_path))
    assert plan.needed and plan.from_version == 1
    assert plan.games == len(raw["games"])
    assert plan.sessions == 123
    assert not (tmp_path / "state").exists()
    assert (tmp_path / "library.json").exists()

    report = migrations.apply(layout_for(tmp_path), plan_only=True)
    assert report.applied is False
    assert not (tmp_path / "state").exists()


def test_second_load_sees_v2_without_remigrating(tmp_path: pathlib.Path) -> None:
    make_v1(tmp_path)
    open_store(tmp_path)
    store, report = open_store(tmp_path)
    assert report["layout"] == "v2"
    assert len(store.games) == 24
    backups = list((tmp_path / "state" / "backup").glob("library-v1-*.json"))
    copies = [p for p in backups if "legacy" not in p.name]
    legacy = [p for p in backups if "legacy" in p.name]
    assert len(copies) == 1, "迁移前复制的那份备份应只有一份"
    assert len(legacy) == 1, "v1 原文件应搬进备份目录"

    # 已经是 v2 时，迁移计划要报出真实规模（而不是 0），否则用户会以为数据丢了
    again = migrations.plan(layout_for(tmp_path))
    assert again.needed is False and again.layout_note == "v2"
    assert (again.games, again.settings, again.sessions) == (24, 39, 123)


def test_settings_write_is_debounced_until_flush(tmp_path: pathlib.Path) -> None:
    store, _ = open_store(tmp_path)          # fresh：没有 v1
    store.settings["accent"] = "#123456"
    store.mark_dirty(settings_only=True)
    assert not (tmp_path / "state" / "settings.json").exists(), "去抖窗口内不该写盘"
    store.flush()
    saved = read_json(tmp_path / "state" / "settings.json", {})
    assert saved["schema_version"] == 2
    assert saved["settings"]["accent"] == "#123456"
    assert not list(tmp_path.glob("state/*.tmp")), "不能留下 tmp 文件"


def test_session_append_only_and_immediate(tmp_path: pathlib.Path) -> None:
    store, _ = open_store(tmp_path)
    for index in range(3):
        store.append_session("game-1", {"ts_start": 100 + index, "ts_end": 200 + index,
                                        "seconds": 100, "source": "session"})
    rows = read_jsonl(tmp_path / "state" / "sessions.jsonl")
    assert [row["game_id"] for row in rows] == ["game-1"] * 3
    assert [row["ts_start"] for row in rows] == [100, 101, 102]


def test_corrupt_library_recovers_from_backup(tmp_path: pathlib.Path) -> None:
    store, _ = open_store(tmp_path)
    store.games.append({"id": "g1", "exe": r"C:\Games\g1\game.exe", "name": "Sample"})
    store.mark_dirty()
    store.flush()
    # 第二次写之前会留 pre-write 备份
    store.games[0]["name"] = "Sample renamed"
    store.mark_dirty()
    store.flush()
    assert list((tmp_path / "state" / "backup").glob("library-*.json"))

    (tmp_path / "state" / "library.json").write_text("{ 坏掉的 json", encoding="utf-8")
    revived, report = open_store(tmp_path)
    assert any("损坏" in note for note in report["notes"])
    assert revived.games, "应该从备份恢复出游戏"
    assert list(tmp_path.glob("state/library.corrupt-*.json")), "损坏文件要留档"


def test_export_redacts_api_key(tmp_path: pathlib.Path) -> None:
    store, _ = open_store(tmp_path)
    store.settings["translate_api_key"] = "sk-secret-value"
    store.settings["accent"] = "#0A84FF"
    payload = store.export_payload(redact=True)
    assert payload["schema_version"] == 2
    assert payload["settings"]["translate_api_key"] == ""
    assert payload["settings"]["accent"] == "#0A84FF"
    assert "sk-secret-value" not in json.dumps(payload, ensure_ascii=False)
    assert store.export_payload(redact=False)["settings"]["translate_api_key"] == "sk-secret-value"


def test_merge_import_dedupes_and_creates_shelves(tmp_path: pathlib.Path) -> None:
    store, _ = open_store(tmp_path)
    store.games.append({"id": "old", "exe": r"C:\Games\a\game.exe", "name": "A"})
    payload = {
        "games": [
            {"id": "x1", "exe": r"C:\Games\a\game.exe", "name": "A dup"},
            {"id": "x2", "exe": r"C:\Games\b\game.exe", "name": "B", "bookshelf_ids": ["s1"]},
        ],
        "bookshelves": [{"id": "s1", "name": "新分类"}],
        "settings": {"accent": "#000000"},
    }
    report = store.merge_import(payload)
    assert report["added"] == 1 and report["skipped"] == 1
    assert report["shelves_created"] == 1
    assert [g["name"] for g in store.games] == ["A", "B"]
    assert store.games[1]["bookshelf_ids"] == [store.shelves[-1]["id"]]
    # 导入不改动本机设置
    assert store.settings.get("accent") != "#000000"


def test_rollback_restores_v1(tmp_path: pathlib.Path) -> None:
    raw = make_v1(tmp_path)
    open_store(tmp_path)
    backup = next((tmp_path / "state" / "backup").glob("library-v1-*.json"))
    # 回滚三步：备份放回原位 → 移除 state → 用旧版启动
    shutil.copy2(backup, tmp_path / "library.json")
    shutil.rmtree(tmp_path / "state")
    reloaded = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert len(reloaded["games"]) == len(raw["games"])

    store, report = open_store(tmp_path)
    assert report["layout"] == "migrated" and len(store.games) == 24


def test_library_facade_round_trip(tmp_path: pathlib.Path) -> None:
    """gl.store.Library 走 StateStore：写入后新实例能读回（不碰真实 data/）。"""
    from gl.store import Library

    store = StateStore(layout_for(tmp_path), autostart=False)
    library = Library(store=store)
    library.add({"id": "g1", "exe": r"C:\Games\g1\game.exe", "name": "Sample"})
    library.set_setting("accent", "#ABCDEF")
    library.record_session("g1", {"ts_start": 1, "ts_end": 2, "seconds": 1, "source": "session"})
    library.flush()

    again = Library(store=StateStore(layout_for(tmp_path), autostart=False))
    assert [g["name"] for g in again.all()] == ["Sample"]
    assert again.settings["accent"] == "#ABCDEF"
    assert len(read_jsonl(tmp_path / "state" / "sessions.jsonl")) == 1
    assert again.load_report["layout"] == "v2"
