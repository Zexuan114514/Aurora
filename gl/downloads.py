"""下载目录监听：把用户下载 / 解压出来的游戏自动识别并交给导入流程。

只处理本地文件，不联网；**不删除、不移动用户的任何文件**。
解压目标限制在下载目录内（`.zip` 走内置解压并做 zip-slip 校验，
`.rar/.7z` 交给本机的 7-Zip / WinRAR）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from . import config

# 网盘 / 浏览器还没下完时的临时后缀，见到就跳过
TEMP_SUFFIXES = (".part", ".crdownload", ".tmp", ".!ut", ".opdownload",
                 ".download", ".partial", ".aria2", ".downloading")
ARCHIVE_SUFFIXES = (".zip", ".rar", ".7z")
# 扫描间隔（秒）
POLL_SECONDS = 5.0
# 连续两次扫描大小与时间都没变，才认为“下载稳定了”
STABLE_HITS = 2


# --------------------------------------------------------------------------- #
# 解压
# --------------------------------------------------------------------------- #
def find_extractor() -> tuple[str, str] | None:
    """返回 (工具类型, 可执行文件)：优先 7-Zip，其次 WinRAR 的 UnRAR。"""
    for name in ("7z", "7za"):
        found = shutil.which(name)
        if found:
            return ("7z", found)
    bases = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
    for base in bases:
        if not base:
            continue
        for kind, rel in (("7z", ("7-Zip", "7z.exe")),
                          ("unrar", ("WinRAR", "UnRAR.exe")),
                          ("winrar", ("WinRAR", "WinRAR.exe"))):
            path = Path(base).joinpath(*rel)
            if path.is_file():
                return (kind, str(path))
    return None


def _norm_name(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _flatten(archive: Path, target: Path) -> None:
    """压缩包自带一层与压缩包同名的目录时摊平，避免出现 A/A/游戏.exe。"""
    try:
        entries = list(target.iterdir())
    except OSError:
        return
    if len(entries) != 1 or not entries[0].is_dir():
        return
    inner = entries[0]
    stem, name = _norm_name(archive.stem), _norm_name(inner.name)
    if not stem or not name or len(name) < 3:
        return
    if name != stem and name not in stem:
        return
    try:
        for item in list(inner.iterdir()):
            dest = target / item.name
            if dest.exists():
                return
            shutil.move(str(item), str(dest))
        inner.rmdir()
    except OSError as exc:
        config.log(f"flatten failed {target}: {exc}")


def _extract_zip(archive: Path, target: Path) -> dict:
    """内置解压 .zip，拒绝目录穿越（zip-slip）。"""
    root = target.resolve()
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in Path(name).parts:
                    return {"ok": False, "error": "unsafe-path", "entry": name}
                if info.flag_bits & 0x1:
                    return {"ok": False, "error": "encrypted"}
            zf.extractall(root)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "target": str(root), "tool": "zipfile"}


def extract(archive: Path, target: Path) -> dict:
    """把压缩包解压到 target（已存在且非空则视为已处理过）。"""
    try:
        if target.exists() and any(target.iterdir()):
            return {"ok": False, "error": "exists", "target": str(target)}
    except OSError:
        pass
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    if archive.suffix.lower() == ".zip":
        result = _extract_zip(archive, target)
        if result.get("ok"):
            _flatten(archive, target)
        return result

    tool = find_extractor()
    if tool is None:
        return {"ok": False, "error": "no-extractor"}
    kind, exe = tool
    if kind == "7z":
        args = [exe, "x", str(archive), f"-o{target}", "-y", "-bso0", "-bsp0"]
    elif kind == "unrar":
        args = [exe, "x", "-y", str(archive), str(target) + os.sep]
    else:
        args = [exe, "x", "-ibck", "-o+", str(archive), str(target) + os.sep]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=900)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        detail = (proc.stderr or b"")[:200].decode("utf-8", "replace")
        return {"ok": False, "error": f"exit {proc.returncode}", "detail": detail}
    _flatten(archive, target)
    return {"ok": True, "target": str(target), "tool": kind}


# --------------------------------------------------------------------------- #
# 监听
# --------------------------------------------------------------------------- #
class DownloadWatcher:
    """后台盯着下载目录，出现新游戏就交给导入回调。"""

    def __init__(self, settings_getter, save_setting, import_fn, status_fn,
                 interval: float = POLL_SECONDS) -> None:
        self._settings = settings_getter      # () -> dict
        self._save = save_setting             # (key, value) -> None
        self._import = import_fn              # (paths: list[str]) -> int
        self._status = status_fn              # (payload: dict) -> None
        self._interval = max(2.0, float(interval))
        self._lock = threading.RLock()
        self._seen: set[str] = set()
        self._stable: dict[str, tuple[int, float, int]] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last: dict = {}
        self._ready = False
        self._baseline_dir = ""

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="aurora-downloads")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def download_dir(self) -> Path:
        settings = self._settings() or {}
        raw = str(settings.get("download_dir") or "").strip()
        return Path(raw) if raw else (config.DATA_DIR / "downloads")

    def status(self) -> dict:
        settings = self._settings() or {}
        return {
            "dir": str(self.download_dir()),
            "watch": bool(settings.get("download_watch", True)),
            "extract": bool(settings.get("download_extract", True)),
            "extractor": (find_extractor() or ("", ""))[0],
            "seen": len(self._seen),
            "last": dict(self._last),
        }

    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # pragma: no cover
                config.log(f"download watcher: {exc}")
            self._stop.wait(self._interval)

    def poll_once(self, manual: bool = False) -> dict:
        """扫一遍下载目录；manual=True 时忽略「已处理」记录（用户主动点的）。"""
        settings = self._settings() or {}
        root = self.download_dir()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        if not manual and not settings.get("download_watch", True):
            return {"ok": True, "skipped": "watch-off", "imported": 0}

        if str(root) != self._baseline_dir:
            fresh = self._ensure_baseline(root, settings)
            if fresh and not manual:
                # 刚给这个目录建基线：这一轮不处理任何东西，避免把旧文件一口气导进来
                self._ready = True
                return {"ok": True, "skipped": "baseline", "imported": 0}

        imported = 0
        handled: list[str] = []
        for entry in sorted(root.iterdir()):
            try:
                if entry.name.startswith("."):
                    continue
                if entry.name in self._seen:
                    continue
                if entry.is_file() and entry.suffix.lower() in TEMP_SUFFIXES:
                    continue
                if entry.is_file() and entry.suffix.lower() not in ARCHIVE_SUFFIXES \
                        and entry.suffix.lower() not in (".exe", ".bat", ".cmd"):
                    self._mark(entry.name)          # 与游戏无关的文件，记下别再查
                    continue
                if not manual and not self._is_stable(entry):
                    continue                        # 可能还在下载 / 解压
                imported += self._handle(entry, settings.get("download_extract", True))
                handled.append(entry.name)
                self._mark(entry.name)
            except OSError as exc:
                config.log(f"download entry failed {entry}: {exc}")
        if handled:
            self._last = {"at": int(time.time()), "names": handled[:6], "count": len(handled)}
            self._emit({"kind": "imported", "names": handled[:6], "count": imported})
        self._ready = True
        return {"ok": True, "imported": imported, "handled": handled}

    def scan_now(self) -> dict:
        return self.poll_once(manual=True)

    # ------------------------------------------------------------------ #
    def _ensure_baseline(self, root: Path, settings: dict) -> bool:
        """换了目录（或第一次跑）时，把现有条目记为基线，不回溯导入。"""
        current = str(root)
        self._baseline_dir = current
        if settings.get("download_baseline_dir") == current:
            self._seen = set(settings.get("download_seen") or [])
            return False
        try:
            names = [p.name for p in root.iterdir()]
        except OSError:
            names = []
        self._seen = set(names)
        self._save("download_baseline_dir", current)
        self._save("download_seen", sorted(self._seen)[-500:])
        return True

    def _mark(self, name: str) -> None:
        if name in self._seen:
            return
        self._seen.add(name)
        self._save("download_seen", sorted(self._seen)[-500:])

    def _is_stable(self, entry: Path) -> bool:
        try:
            stat = entry.stat()
            size, mtime = int(stat.st_size), float(stat.st_mtime)
        except OSError:
            return False
        if entry.is_dir():
            size = 0
        prev = self._stable.get(entry.name)
        hits = (prev[2] + 1) if prev and prev[0] == size and prev[1] == mtime else 1
        self._stable[entry.name] = (size, mtime, hits)
        return hits >= STABLE_HITS

    def _handle(self, entry: Path, allow_extract: bool) -> int:
        name = entry.name
        if entry.is_file() and entry.suffix.lower() in ARCHIVE_SUFFIXES:
            if not allow_extract:
                self._emit({"kind": "warn", "text": f"检测到压缩包 {name}，但自动解压已关闭"})
                return 0
            target = entry.with_suffix("")
            res = extract(entry, target)
            if not res.get("ok"):
                err = res.get("error") or "unknown"
                text = {
                    "no-extractor": f"检测到 {name}，但本机没找到解压工具（装个 7-Zip 或 WinRAR 即可）",
                    "encrypted": f"{name} 是加密压缩包，请手动解压",
                    "exists": f"{name} 已经有同名文件夹了，跳过",
                    "unsafe-path": f"{name} 内含不安全的路径，已拒绝解压",
                }.get(err, f"{name} 解压失败：{err}")
                self._emit({"kind": "warn", "text": text})
                return 0
            self._emit({"kind": "extracted", "name": name, "target": res.get("target", "")})
            path = res.get("target") or str(target)
            # 解压出来的文件夹等于同一个游戏，标记掉免得下一轮又当成新内容导一次
            self._mark(Path(path).name)
            return self._import_paths([path])
        return self._import_paths([str(entry)])

    def _import_paths(self, paths: list[str]) -> int:
        clean = [p for p in paths if p]
        if not clean:
            return 0
        try:
            return int(self._import(clean) or 0)
        except Exception as exc:
            config.log(f"download import failed: {exc}")
            self._emit({"kind": "warn", "text": f"导入失败：{exc}"})
            return 0

    def _emit(self, payload: dict) -> None:
        try:
            self._status(payload)
        except Exception:
            pass
