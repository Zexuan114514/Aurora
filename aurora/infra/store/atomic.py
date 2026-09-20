"""原子写、备份与损坏留档：写 tmp → flush + fsync → replace → 回读校验。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path


def checksum(path: Path) -> str:
    """文件的 sha256（备份校验用）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default=None):
    """读 JSON；文件不存在或损坏时返回 default（不抛）。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path: Path, data, *, fsync: bool = True, verify: bool = True) -> None:
    """原子写：先写同目录 tmp，再 replace；replace 后回读确认可解析。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())
    os.replace(tmp, path)
    if verify and read_json(path, None) is None:
        raise OSError(f"写入校验失败（回读不可解析）：{path}")


def append_jsonl(path: Path, record: dict, *, fsync: bool = True) -> None:
    """追加一行 JSONL 并立即落盘（会话记录用）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())


def read_jsonl(path: Path) -> list[dict]:
    """读 JSONL；坏行跳过（不因为一行坏了丢整份历史）。"""
    rows: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except Exception:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
    except FileNotFoundError:
        return []
    except Exception:
        return rows
    return rows


def backup_file(source: Path, backup_dir: Path, *, tag: str = "") -> Path:
    """把文件复制进备份目录（带时间戳），复制后校验 sha256 一致。"""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    middle = f"-{tag}" if tag else ""
    target = backup_dir / f"{source.stem}{middle}-{stamp}{source.suffix}"
    if target.exists():
        target = backup_dir / f"{source.stem}{middle}-{stamp}-{int(time.time() * 1000) % 1000:03d}{source.suffix}"
    shutil.copy2(source, target)
    if checksum(source) != checksum(target):
        try:
            target.unlink()
        except OSError:
            pass
        raise OSError(f"备份校验失败：{source} → {target}")
    return target


def newest_backup(backup_dir: Path, pattern: str) -> Path | None:
    """按修改时间取最新的匹配备份。"""
    try:
        rows = [p for p in backup_dir.glob(pattern) if p.is_file()]
    except Exception:
        return None
    if not rows:
        return None
    return max(rows, key=lambda p: p.stat().st_mtime)


def quarantine(path: Path, *, tag: str = "corrupt") -> Path | None:
    """把损坏文件改名留档（绝不删除用户数据）。"""
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.{tag}-{stamp}{path.suffix}")
    try:
        os.replace(path, target)
    except OSError:
        return None
    return target
