"""启动可执行文件并跟踪运行状态。"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from pathlib import Path

from aurora.domain import session_rules

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


# 轮询间隔：够快能及时反映退出，又不至于一直抓进程表
POLL_SECONDS = 1.5
# 启动后多久内必须找到「游戏本体」，否则认为它已经退出
STARTUP_GRACE = 20.0
# 游戏本体消失后等多久才认定结束（防止重启子进程的瞬间误判）
EXIT_GRACE = 3.0


class ProcessManager:
    """记录由本启动器拉起的游戏，并按**进程树**判断它是不是还在跑。

    引导 exe / Locale Emulator 拉起游戏后会自己退出，所以不能用 Popen 的
    存活状态代表游戏：这里每隔 1.5s 找一次「镜像路径 = 游戏 exe」的进程
    （含启动进程的整棵子树），找到才算真正在运行。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running: dict[str, dict] = {}
        self._on_found = None      # (game_id, pid) -> None
        self._on_exit = None       # (game_id, seconds) -> None

    def set_callbacks(self, on_found=None, on_exit=None) -> None:
        self._on_found = on_found
        self._on_exit = on_exit

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
                "launched_pid": pid,
                "game_pids": {pid},
                "baseline": set(),
                "exe": exe,
                "finished": False,
                "gone_at": 0.0,
                "reattached": True,
                "matched_by": "reattached",
                "game_id": game["id"],
            }
        self._spawn_monitor(game["id"])
        return True

    def is_running(self, game_id: str) -> bool:
        with self._lock:
            entry = self._running.get(game_id)
            return bool(entry) and not entry.get("finished")

    def _finalize(self, game_id: str) -> None:
        """结束会话并回调（自然退出与手动结束共用；重复调用只生效一次）。"""
        with self._lock:
            entry = self._running.pop(game_id, None)
            if entry is None:
                return
            entry["finished"] = True
            entry["ended_at"] = time.time()
        # 以「本体真正消失的时刻」结算，别把退出宽限期算进玩家时长（公式见 domain/session_rules）
        seconds = session_rules.session_seconds(
            started_at=entry.get("started_at") or 0.0,
            gone_at=entry.get("gone_at") or 0.0,
            ended_at=entry.get("ended_at") or 0.0,
            now=time.time(),
        )
        if self._on_exit:
            try:
                self._on_exit(game_id, seconds)
            except Exception as exc:
                config.log(f"session exit callback failed: {exc}")

    def running_ids(self) -> list[str]:
        with self._lock:
            return [gid for gid, entry in self._running.items() if not entry.get("finished")]

    def game_pid(self, game_id: str) -> int:
        with self._lock:
            entry = self._running.get(game_id)
        if not entry:
            return 0
        pids = sorted(entry.get("game_pids") or [])
        return pids[0] if pids else 0

    def start(self, game: dict, launcher: list[str] | None = None) -> dict:
        """启动游戏；launcher 不为空时用它代替直接启动（如 Locale Emulator）。"""
        game_id = game["id"]
        if self.is_running(game_id):
            return {"ok": False, "error": "already-running"}

        exe = Path(game["exe"])
        if not exe.exists():
            return {"ok": False, "error": "missing-exe", "path": str(exe)}

        workdir = game.get("workdir") or str(exe.parent)
        extra = _split_args((game.get("launch_args") or "").strip())
        if launcher:
            args = [str(part) for part in launcher] + extra
        elif exe.suffix.lower() in (".bat", ".cmd"):
            # 批处理必须交给 cmd.exe，否则 CreateProcess 起不来
            args = [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(exe)] + extra
        else:
            args = [str(exe)] + extra

        try:
            from . import proctree

            baseline = proctree.matching_pids(exe)
        except Exception:
            baseline = set()

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

        started = time.time()
        with self._lock:
            self._running[game_id] = {
                "proc": proc,
                "started_at": started,
                "launched_pid": proc.pid,
                "game_pids": set(),
                "baseline": baseline,
                "exe": str(exe),
                "finished": False,
                "gone_at": 0.0,
                "game_id": game_id,
            }
        self._spawn_monitor(game_id)
        return {"ok": True, "pid": proc.pid, "started_at": started}

    def _spawn_monitor(self, game_id: str) -> None:
        threading.Thread(target=self._monitor, args=(game_id,), daemon=True,
                         name=f"aurora-session-{game_id[:6]}").start()

    def _monitor(self, game_id: str) -> None:
        while True:
            time.sleep(POLL_SECONDS)
            with self._lock:
                entry = self._running.get(game_id)
            if not entry or entry.get("finished"):
                return
            try:
                done = self._tick(entry)
            except Exception as exc:
                config.log(f"session monitor error: {exc}")
                continue
            if not done:
                continue
            self._finalize(game_id)
            return

    def _tick(self, entry: dict) -> bool:
        """返回 True 表示这次会话已经结束。"""
        from . import proctree

        now = time.time()
        exe = entry.get("exe") or ""
        rows = proctree.snapshot()
        pids = set(entry.get("game_pids") or set())
        baseline = set(entry.get("baseline") or set())
        launched = int(entry.get("launched_pid") or 0)
        # 引导 exe / LEProc / cmd 都可能先退出，真正游戏是它的子进程且名字不同，
        # 所以除了「镜像路径完全一致」，还要把启动进程的整棵子树算进来
        tree = {pid for pid in (proctree.descendants(launched, rows) - baseline) if pid}
        tree.discard(launched)
        by_path = proctree.matching_pids(exe, rows) - baseline

        # 注意：只有「从来没找到过本体」才走启动宽限；找到过再消失要走退出宽限，
        # 否则本体一退出 pids 就空了，会被误当成「还没启动完」，白等满 STARTUP_GRACE。
        if not pids and not entry.get("matched_by"):
            # 还没找到游戏本体：优先精确匹配，其次看启动进程的子树
            candidates = by_path or tree
            if candidates:
                entry["game_pids"] = candidates
                # 记下"当时是怎么认出来的"：按路径认出的就别再理会启动器的其它子进程
                entry["matched_by"] = "path" if by_path else "tree"
                entry["gone_at"] = 0.0
                config.log(f"session {entry.get('game_id')} game pid(s)={sorted(candidates)}")
                if self._on_found:
                    try:
                        self._on_found(entry.get("game_id"), sorted(candidates)[0])
                    except Exception as exc:
                        config.log(f"session found callback failed: {exc}")
                return False
            return (now - float(entry.get("started_at") or now)) > STARTUP_GRACE

        alive = {pid for pid in pids if proctree.is_alive(pid)}
        alive |= by_path
        if entry.get("matched_by") == "tree":
            alive |= tree
        entry["game_pids"] = alive
        if alive:
            entry["gone_at"] = 0.0
            return False
        if not entry.get("gone_at"):
            entry["gone_at"] = now
            return False
        return (now - float(entry["gone_at"])) >= EXIT_GRACE

    def stop(self, game_id: str) -> dict:
        with self._lock:
            entry = self._running.get(game_id)
        if not entry:
            return {"ok": False, "error": "not-running"}
        pids = set(entry.get("game_pids") or set())
        launched = int(entry.get("launched_pid") or 0)
        if launched:
            pids.add(launched)
        killed: list[int] = []
        for pid in sorted(pids):
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=0x08000000,
                    timeout=10,
                )
                killed.append(pid)
            except Exception as exc:
                config.log(f"taskkill failed [{pid}]: {exc}")
        if not killed:
            proc = entry.get("proc")
            try:
                if proc is not None:
                    proc.terminate()
            except Exception:
                pass
        self._finalize(game_id)
        return {"ok": True, "pid": launched or (killed[0] if killed else 0), "killed": killed}

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
