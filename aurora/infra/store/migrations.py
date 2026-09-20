"""v1 → v2 迁移：检测、干跑计划、执行（备份 → 拆分 → 校验 → 提交）。"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import backup_file, checksum, read_json, write_json
from .paths import Layout

SCHEMA_VERSION = 2


class MigrationError(RuntimeError):
    """迁移无法安全进行（此时不会写任何 v2 文件）。"""


@dataclass
class MigrationPlan:
    """迁移计划：既能干跑给用户看，也能直接执行。"""

    needed: bool
    from_version: int | None
    layout_note: str
    games: int = 0
    bookshelves: int = 0
    settings: int = 0
    sessions: int = 0
    has_legacy_glossary: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "needed": self.needed,
            "from_version": self.from_version,
            "layout": self.layout_note,
            "games": self.games,
            "bookshelves": self.bookshelves,
            "settings": self.settings,
            "sessions": self.sessions,
            "legacy_glossary": self.has_legacy_glossary,
            "notes": list(self.notes),
        }


@dataclass
class MigrationReport:
    plan: MigrationPlan
    applied: bool
    backup: Path | None = None
    backup_checksum: str = ""
    legacy_moved_to: Path | None = None
    glossary_copied_to: Path | None = None

    def as_dict(self) -> dict:
        return {
            **self.plan.as_dict(),
            "applied": self.applied,
            "backup": str(self.backup) if self.backup else "",
            "backup_checksum": self.backup_checksum,
            "legacy_moved_to": str(self.legacy_moved_to) if self.legacy_moved_to else "",
            "glossary_copied_to": str(self.glossary_copied_to) if self.glossary_copied_to else "",
        }


def detect(layout: Layout) -> tuple[bool, int | None, str]:
    """返回（是否需要迁移, 现有版本, 说明）。

    v2 = `state/settings.json` 或 `state/library.json` 已存在；
    v1 = 只有 `<root>/library.json`；fresh = 都没有。
    """
    if layout.settings_file.exists() or layout.library_file.exists():
        return False, SCHEMA_VERSION, "v2"
    if layout.legacy_library.exists():
        return True, 1, "v1"
    return False, None, "fresh"


def plan(layout: Layout) -> MigrationPlan:
    """只读地算出迁移计划；v1 文件不可解析时抛 MigrationError。"""
    needed, version, note = detect(layout)
    result = MigrationPlan(needed=needed, from_version=version, layout_note=note,
                           has_legacy_glossary=layout.legacy_glossary.exists())
    if not needed:
        return result

    raw = read_json(layout.legacy_library, None)
    if not isinstance(raw, dict):
        raise MigrationError(f"v1 库无法解析：{layout.legacy_library}")
    games = raw.get("games")
    if not isinstance(games, list):
        raise MigrationError("v1 库里没有 games 数组")

    result.games = len(games)
    result.bookshelves = len(raw.get("bookshelves") or [])
    result.settings = len(raw.get("settings") or {})
    result.sessions = sum(len(g.get("sessions") or []) for g in games if isinstance(g, dict))
    for index, game in enumerate(games):
        if not isinstance(game, dict):
            result.notes.append(f"第 {index + 1} 条不是对象，迁移时原样保留")
    if result.has_legacy_glossary:
        result.notes.append("检测到 v1 术语表，会复制到 vntext/glossary.json（保留原文件）")
    return result


def _session_rows(games: list[dict]) -> list[dict]:
    """把每个游戏内嵌的 sessions 摊平成追加式记录。"""
    rows: list[dict] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("id") or "")
        for item in game.get("sessions") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "game_id": game_id,
                "ts_start": int(item.get("started_at") or 0),
                "ts_end": int(item.get("ended_at") or 0),
                "seconds": int(item.get("seconds") or 0),
                "source": "migrated-v1",
            })
    return rows


def apply(layout: Layout, *, plan_only: bool = False) -> MigrationReport:
    """执行（或干跑）迁移。任何一步失败都不会留下半套 v2 数据。"""
    current = plan(layout)
    if not current.needed:
        return MigrationReport(plan=current, applied=False)
    if plan_only:
        return MigrationReport(plan=current, applied=False)

    raw = read_json(layout.legacy_library, None)
    if not isinstance(raw, dict):
        raise MigrationError("v1 库在迁移过程中变得不可读，已中止")

    backup = backup_file(layout.legacy_library, layout.backup, tag="v1")
    digest = checksum(layout.legacy_library)

    games = list(raw.get("games") or [])
    shelves = list(raw.get("bookshelves") or [])
    settings = dict(raw.get("settings") or {})
    rows = _session_rows(games)

    written: list[Path] = []
    try:
        write_json(layout.settings_file, {"schema_version": SCHEMA_VERSION, "settings": settings})
        written.append(layout.settings_file)
        write_json(layout.library_file, {"schema_version": SCHEMA_VERSION,
                                         "games": games, "bookshelves": shelves})
        written.append(layout.library_file)

        layout.sessions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(layout.sessions_file, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        written.append(layout.sessions_file)

        # 回读校验：字段数与迁移前一致才算成功
        check_settings = read_json(layout.settings_file, {}) or {}
        check_library = read_json(layout.library_file, {}) or {}
        if len(check_settings.get("settings") or {}) != len(settings):
            raise MigrationError("迁移后 settings 数量不一致")
        if len(check_library.get("games") or []) != len(games):
            raise MigrationError("迁移后 games 数量不一致")
    except Exception:
        for path in written:
            try:
                path.unlink()
            except OSError:
                pass
        raise

    glossary_copy: Path | None = None
    if layout.legacy_glossary.exists() and not layout.glossary_file.exists():
        try:
            layout.glossary_file.parent.mkdir(parents=True, exist_ok=True)
            with open(layout.legacy_glossary, "r", encoding="utf-8") as src:
                payload = src.read()
            with open(layout.glossary_file, "w", encoding="utf-8") as dst:
                dst.write(payload)
            glossary_copy = layout.glossary_file
        except Exception:
            glossary_copy = None

    moved: Path | None = None
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = layout.backup / f"library-v1-legacy-{stamp}.json"
        os.replace(layout.legacy_library, target)
        moved = target
    except OSError:
        moved = None

    return MigrationReport(plan=current, applied=True, backup=backup,
                           backup_checksum=digest, legacy_moved_to=moved,
                           glossary_copied_to=glossary_copy)
