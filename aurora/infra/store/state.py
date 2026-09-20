"""状态存储（StateStorePort 的 JSON 实现）：单写者 + 去抖 + 损坏恢复 + 导入导出。

设计要点（见 docs/architecture/contracts/data-schema-v2.md）：
  * `settings.json` / `library.json` / `sessions.jsonl` 三个真相文件；
  * 写入走「tmp → fsync → replace → 回读校验」，退出/会话结束前强制 flush；
  * 去抖默认 300ms（库）/ 500ms（设置），避免改一个设置重写整个库；
  * 解析失败时用最近备份恢复，损坏文件改名留档，绝不静默丢数据。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from . import migrations
from .atomic import (append_jsonl, backup_file, newest_backup, quarantine,
                     read_json, read_jsonl, write_json)
from .paths import Layout, VERSION, ensure_dirs

#: 导出时会被抹掉的设置键（密钥不进导出文件，见 ADR-0011）
REDACTED_SETTING_KEYS = ("translate_api_key",)
#: 备份保留份数（按前缀各自计算）
KEEP_BACKUPS = 3


class SystemClock:
    """默认时钟（测试里换成假时钟）。"""

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class StateStore:
    """游戏库 / 设置 / 会话历史的持久化实现。"""

    def __init__(self, layout: Layout, *, clock=None, debounce_ms: int = 300,
                 settings_debounce_ms: int = 500, autostart: bool = True,
                 migrate: bool = True) -> None:
        self.layout = layout
        self.clock = clock or SystemClock()
        self.debounce_ms = int(debounce_ms)
        self.settings_debounce_ms = int(settings_debounce_ms)
        self.games: list[dict] = []
        self.shelves: list[dict] = []
        self.settings: dict = {}

        self._migrate = migrate
        self._dirty: set[str] = set()
        self._cond = threading.Condition()
        self._stop = False
        self._thread: threading.Thread | None = None
        self._deadline = 0.0
        self._backed_up: set[str] = set()
        self._notes: list[str] = []
        ensure_dirs(layout)
        if autostart:
            self._start_writer()

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def _start_writer(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="aurora-state-writer")
        self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._cond:
                if self._stop:
                    return
                if not self._dirty:
                    self._cond.wait(1.0)
                    continue
                wait = self._deadline - self.clock.now()
                if wait > 0:
                    self._cond.wait(min(wait, 1.0))
                    continue
            self._write_now()

    def load(self) -> dict:
        """装载状态；v1 存在且允许迁移时先迁移。"""
        notes: list[str] = []
        report: dict = {"notes": notes}
        needed, version, note = migrations.detect(self.layout)
        if needed and self._migrate:
            try:
                result = migrations.apply(self.layout)
                report["layout"] = "migrated"
                report["backup"] = str(result.backup or "")
                notes.append(f"已从 v1 迁移（备份：{result.backup}）")
            except Exception as exc:
                notes.append(f"迁移失败，按空库启动：{exc}")
                report["layout"] = "error"
        else:
            report["layout"] = note

        self.settings = self._load_settings(notes)
        library = self._load_library(notes)
        self.games = list(library.get("games") or [])
        self.shelves = list(library.get("bookshelves") or [])
        sessions = read_jsonl(self.layout.sessions_file)

        report.update({
            "games": len(self.games),
            "bookshelves": len(self.shelves),
            "settings": len(self.settings),
            "sessions": len(sessions),
            "notes": notes,
        })
        self._notes = notes
        return report

    def _load_settings(self, notes: list[str]) -> dict:
        raw = read_json(self.layout.settings_file, None)
        if raw is None and self.layout.settings_file.exists():
            restored = self._recover(self.layout.settings_file, "settings-*.json")
            notes.append(f"settings.json 损坏，{'已用备份恢复' if restored else '回退为空设置'}")
            raw = read_json(self.layout.settings_file, None)
        payload = raw.get("settings") if isinstance(raw, dict) else None
        return dict(payload) if isinstance(payload, dict) else {}

    def _load_library(self, notes: list[str]) -> dict:
        raw = read_json(self.layout.library_file, None)
        if raw is None and self.layout.library_file.exists():
            restored = self._recover(self.layout.library_file, "library-*.json")
            notes.append(f"library.json 损坏，{'已用备份恢复' if restored else '回退为空库'}")
            raw = read_json(self.layout.library_file, None)
        if isinstance(raw, dict):
            return raw
        return {"games": [], "bookshelves": []}

    def _recover(self, path: Path, pattern: str) -> bool:
        """用最近备份恢复；坏的留档。返回是否恢复成功。"""
        backup = newest_backup(self.layout.backup, pattern)
        quarantine(path, tag="corrupt")
        if backup is None:
            return False
        try:
            payload = read_json(backup, None)
            if payload is None:
                return False
            write_json(path, payload)
            return True
        except Exception:
            return False

    def stats(self) -> dict:
        return {
            "layout": str(self.layout.root),
            "state_dir": str(self.layout.state),
            "games": len(self.games),
            "bookshelves": len(self.shelves),
            "settings": len(self.settings),
            "sessions": len(read_jsonl(self.layout.sessions_file)),
            "dirty": sorted(self._dirty),
            "notes": list(self._notes),
        }

    # ------------------------------------------------------------------ #
    # 写入
    # ------------------------------------------------------------------ #
    def mark_dirty(self, *, settings_only: bool = False) -> None:
        """标记待写；真正的写由去抖窗口或 flush() 触发。"""
        with self._cond:
            self._dirty.add("settings" if settings_only else "library")
            if settings_only:
                self._dirty.add("settings")
            delay = self.settings_debounce_ms if settings_only else self.debounce_ms
            self._deadline = self.clock.now() + max(delay, 0) / 1000.0
            self._cond.notify_all()

    def flush(self, *, timeout: float = 5.0) -> None:
        """强制把待写内容落盘（会话结束、启动/结束游戏、退出前调用）。"""
        with self._cond:
            if not self._dirty:
                return
            self._deadline = 0.0
            self._cond.notify_all()
        if self._thread is None:
            self._write_now()
            return
        deadline = self.clock.monotonic() + max(timeout, 0.1)
        while self.clock.monotonic() < deadline:
            with self._cond:
                if not self._dirty:
                    return
            time.sleep(0.01)

    def close(self) -> None:
        """停止写线程并完成最后一次落盘。"""
        try:
            self.flush()
        except Exception:
            pass
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None

    def _write_now(self) -> None:
        """写者：把脏文件按需写出（同一时刻只有一个线程执行）。"""
        with self._cond:
            pending = set(self._dirty)
            self._dirty.clear()
        if not pending:
            return
        self._safeguard(pending)
        if "library" in pending:
            write_json(self.layout.library_file,
                       {"schema_version": migrations.SCHEMA_VERSION,
                        "games": self.games, "bookshelves": self.shelves})
        if "settings" in pending:
            write_json(self.layout.settings_file,
                       {"schema_version": migrations.SCHEMA_VERSION, "settings": self.settings})

    def _safeguard(self, pending: set[str]) -> None:
        """覆盖已有文件之前先留一份备份（每个文件、每个进程只做一次）。

        规则：准备写某个文件时，如果它**已存在**且本进程还没为它备份过，
        就先复制到 state/backup/<name>-pre-write-<ts>.json；保底最近 3 份。
        """
        targets = []
        if "library" in pending:
            targets.append((self.layout.library_file, "library-*.json"))
        if "settings" in pending:
            targets.append((self.layout.settings_file, "settings-*.json"))
        for path, pattern in targets:
            key = path.name
            if key in self._backed_up:
                continue
            try:
                if not path.exists():
                    continue          # 还没有旧文件可备份，下次再检查
                backup_file(path, self.layout.backup, tag="pre-write")
                self._prune_backups(pattern)
                self._backed_up.add(key)
            except Exception:
                continue

    def _prune_backups(self, pattern: str) -> None:
        try:
            rows = sorted((p for p in self.layout.backup.glob(pattern) if p.is_file()),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            return
        for stale in rows[KEEP_BACKUPS:]:
            try:
                stale.unlink()
            except OSError:
                continue

    # ------------------------------------------------------------------ #
    # 会话历史
    # ------------------------------------------------------------------ #
    def append_session(self, game_id: str, record: dict) -> None:
        """追加一条会话记录并立即落盘（崩溃最多丢最后一条）。"""
        row = {"game_id": str(game_id), **{k: record[k] for k in record}}
        append_jsonl(self.layout.sessions_file, row)

    # ------------------------------------------------------------------ #
    # 导入 / 导出
    # ------------------------------------------------------------------ #
    def export_payload(self, *, redact: bool = True) -> dict:
        settings = dict(self.settings)
        if redact:
            for key in REDACTED_SETTING_KEYS:
                if key in settings:
                    settings[key] = ""
        return {
            "app": "Aurora",
            "version": VERSION,
            "schema_version": migrations.SCHEMA_VERSION,
            "exported_at": int(self.clock.now()),
            "games": [dict(g) for g in self.games],
            "bookshelves": [dict(s) for s in self.shelves],
            "settings": settings,
        }

    def merge_import(self, payload: dict) -> dict:
        """按 exe 路径合并导入（分类按名字合并，不覆盖已有条目）。"""
        if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
            return {"added": 0, "skipped": 0, "shelves_created": 0, "games": [], "error": "bad-file"}

        shelf_map: dict[str, str] = {}
        created = 0
        for row in payload.get("bookshelves") or []:
            if not isinstance(row, dict):
                continue
            old_id = str(row.get("id") or "")
            name = str(row.get("name") or "").strip()
            if not old_id or not name:
                continue
            existing = next((s for s in self.shelves if str(s.get("name", "")).lower() == name.lower()), None)
            if existing:
                shelf_map[old_id] = str(existing.get("id") or "")
            else:
                shelf = {"id": uuid.uuid4().hex[:12], "name": name,
                         "created_at": int(self.clock.now())}
                self.shelves.append(shelf)
                shelf_map[old_id] = shelf["id"]
                created += 1

        known = {str(g.get("exe") or "").lower() for g in self.games}
        ids = {str(g.get("id") or "") for g in self.games}
        added: list[dict] = []
        skipped = 0
        for row in payload["games"]:
            if not isinstance(row, dict):
                continue
            exe = str(row.get("exe") or "")
            if not exe or exe.lower() in known:
                skipped += 1
                continue
            record = dict(row)
            if not record.get("id") or str(record["id"]) in ids:
                record["id"] = uuid.uuid4().hex[:12]
            ids.add(str(record["id"]))
            known.add(exe.lower())
            record.setdefault("images", [])
            record.setdefault("background", "")
            record["bookshelf_ids"] = [shelf_map[x] for x in (record.get("bookshelf_ids") or [])
                                       if x in shelf_map]
            self.games.append(record)
            added.append(record)

        if added or created:
            self.mark_dirty()
            self.flush()
        return {"added": len(added), "skipped": skipped, "shelves_created": created,
                "games": [dict(g) for g in added]}


def summarize(payload: dict) -> str:
    """给 `--check-migration` 之类的人类可读输出。"""
    return json.dumps(payload, ensure_ascii=False, indent=2)
