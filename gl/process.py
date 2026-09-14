"""启动可执行文件并跟踪运行状态。"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from pathlib import Path

from . import config

CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
_kernel32.OpenProcess.restype = ctypes.c_void_p
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_kernel32.CloseHandle.restype = ctypes.c_int
_kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
    ctypes.POINTER(ctypes.c_uint32),
]
_kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
_kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_kernel32.WaitForSingleObject.restype = ctypes.c_uint32


# --------------------------------------------------------------------------- #
# 进程查询（用于启动器重启后确认游戏是否还在运行）
# --------------------------------------------------------------------------- #
def _open(pid: int, access: int):
    try:
        handle = _kernel32.OpenProcess(access, False, int(pid))
    except Exception:
        return None
    return handle or None


def process_image(pid: int) -> str:
    """该 pid 对应的可执行文件全路径；进程不存在 / 无权限时返回空串。"""
    handle = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_uint32(len(buf))
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    except Exception:
        return ""
    finally:
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            pass


def pid_matches(pid: int, exe: str) -> bool:
    """pid 是否仍然对应同一个可执行文件（避免 pid 复用造成的误判）。"""
    if not pid or not exe:
        return False
    path = process_image(pid)
    if not path:
        return False
    try:
        return os.path.normcase(str(Path(path).resolve())) == os.path.normcase(
            str(Path(exe).resolve()))
    except Exception:
        return os.path.normcase(path) == os.path.normcase(str(exe))


class ForeignProcess:
    """启动器之外（上次运行）拉起的进程，重新接管后仍可计时与结束。"""

    def __init__(self, pid: int, exe: str) -> None:
        self.pid = int(pid)
        self.exe = str(exe)
        self._handle = _open(self.pid, SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION)

    def alive(self) -> bool:
        if not self._handle:
            return False
        try:
            return _kernel32.WaitForSingleObject(self._handle, 0) == WAIT_TIMEOUT
        except Exception:
            return False

    def poll(self):
        """None 表示仍在运行（与 subprocess.Popen.poll 语义一致）。"""
        return None if self.alive() else 0

    def wait(self, timeout: float | None = None):
        if not self._handle:
            return 0
        try:
            ms = INFINITE if timeout is None else int(max(0.0, timeout) * 1000)
            _kernel32.WaitForSingleObject(self._handle, ms)
        except Exception:
            pass
        return 0

    def terminate(self) -> None:
        try:
            subprocess.run(["taskkill", "/PID", str(self.pid), "/T", "/F"],
                           capture_output=True, creationflags=0x08000000, timeout=10)
        except Exception as exc:
            config.log(f"foreign terminate failed: {exc}")

    def __del__(self):  # pragma: no cover
        try:
            if self._handle:
                _kernel32.CloseHandle(self._handle)
        except Exception:
            pass


class ProcessManager:
    """记录由本启动器拉起的进程。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running: dict[str, dict] = {}

    def attach(self, game: dict, started_at: float) -> bool:
        """重新接管一个仍在运行的进程（启动器重启场景）。"""
        pid = int(game.get("play_pid") or 0)
        exe = str(game.get("exe") or "")
        if not pid_matches(pid, exe):
            return False
        with self._lock:
            self._running[game["id"]] = {
                "proc": ForeignProcess(pid, exe),
                "started_at": float(started_at or time.time()),
                "reattached": True,
            }
        return True

    def is_running(self, game_id: str) -> bool:
        with self._lock:
            entry = self._running.get(game_id)
            if not entry:
                return False
            if entry["proc"].poll() is None:
                return True
            self._finalize(game_id)
            return False

    def _finalize(self, game_id: str) -> None:
        entry = self._running.pop(game_id, None)
        if not entry:
            return
        entry["ended_at"] = time.time()

    def running_ids(self) -> list[str]:
        with self._lock:
            for game_id in list(self._running):
                entry = self._running.get(game_id)
                if entry and entry["proc"].poll() is not None:
                    self._finalize(game_id)
            return list(self._running)

    def start(self, game: dict) -> dict:
        game_id = game["id"]
        if self.is_running(game_id):
            return {"ok": False, "error": "already-running"}

        exe = Path(game["exe"])
        if not exe.exists():
            return {"ok": False, "error": "missing-exe", "path": str(exe)}

        workdir = game.get("workdir") or str(exe.parent)
        if exe.suffix.lower() in (".bat", ".cmd"):
            # 批处理必须交给 cmd.exe，否则 CreateProcess 起不来
            args = [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(exe)]
        else:
            args = [str(exe)]
        extra = (game.get("launch_args") or "").strip()
        if extra:
            args.extend(_split_args(extra))

        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            proc = subprocess.Popen(
                args,
                cwd=workdir if os.path.isdir(workdir) else str(exe.parent),
                close_fds=True,
                creationflags=flags,
            )
        except Exception as exc:
            config.log(f"launch failed [{exe}]: {exc}")
            return {"ok": False, "error": str(exc)}

        with self._lock:
            self._running[game_id] = {"proc": proc, "started_at": time.time()}
        return {"ok": True, "pid": proc.pid, "started_at": time.time()}

    def stop(self, game_id: str) -> dict:
        with self._lock:
            entry = self._running.get(game_id)
        if not entry:
            return {"ok": False, "error": "not-running"}
        pid = entry["proc"].pid
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=0x08000000,
                timeout=10,
            )
        except Exception as exc:
            config.log(f"taskkill failed: {exc}")
            try:
                entry["proc"].terminate()
            except Exception:
                pass
        self._finalize(game_id)
        return {"ok": True, "pid": pid}

    def play_seconds(self, game_id: str) -> float:
        with self._lock:
            entry = self._running.get(game_id)
        if not entry:
            return 0.0
        return max(0.0, time.time() - entry["started_at"])

    def started_at(self, game_id: str) -> float:
        """本次会话的开始时间（没在运行则返回 0）。"""
        with self._lock:
            entry = self._running.get(game_id)
        return float(entry["started_at"]) if entry else 0.0


def _split_args(text: str) -> list[str]:
    """按 Windows 命令行规则粗分参数。"""
    import re

    return [part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part
            for part in re.findall(r'"[^"]*"|\S+', text)]


def reveal(path: str) -> None:
    target = Path(path)
    folder = target if target.is_dir() else target.parent
    try:
        subprocess.Popen(["explorer", "/select,", str(target if target.exists() else folder)])
    except Exception as exc:
        config.log(f"reveal failed: {exc}")
