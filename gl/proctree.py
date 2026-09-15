"""进程树工具：判断「游戏本体」是不是还在运行。

galgame 常见「引导 exe / Locale Emulator 立刻退出，真正游戏是子进程」的结构，
只盯着 Popen 返回的 PID 会把这种情况误判成「游戏已结束」。
这里用 Toolhelp32 抓进程表，配合 gl.process 的镜像路径查询来定位游戏本体。
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from . import process as _process

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD

_INVALID_HANDLE = ctypes.c_void_p(-1).value


def snapshot() -> list[dict]:
    """一次进程快照：[{pid, ppid, name}]；失败返回空表。"""
    rows: list[dict] = []
    handle = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not handle or handle == _INVALID_HANDLE:
        return rows
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(handle, ctypes.byref(entry)):
            return rows
        while True:
            rows.append({
                "pid": int(entry.th32ProcessID),
                "ppid": int(entry.th32ParentProcessID),
                "name": str(entry.szExeFile or ""),
            })
            if not _kernel32.Process32NextW(handle, ctypes.byref(entry)):
                break
    finally:
        _kernel32.CloseHandle(handle)
    return rows


def descendants(root_pid: int, rows: list[dict] | None = None) -> set[int]:
    """root_pid 的整棵子树（含自己）。"""
    if not root_pid:
        return set()
    rows = rows if rows is not None else snapshot()
    children: dict[int, list[int]] = {}
    for row in rows:
        children.setdefault(row["ppid"], []).append(row["pid"])
    out = {int(root_pid)}
    stack = [int(root_pid)]
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def matching_pids(exe: str | Path, rows: list[dict] | None = None) -> set[int]:
    """镜像路径等于 exe 的进程（先按文件名过滤，避免逐个 OpenProcess）。"""
    target = Path(str(exe))
    if not str(target):
        return set()
    name = target.name.lower()
    rows = rows if rows is not None else snapshot()
    out: set[int] = set()
    for row in rows:
        if row["name"].lower() != name:
            continue
        image = _process.process_image(row["pid"])
        if not image:
            continue
        try:
            same = os.path.normcase(str(Path(image).resolve())) == \
                os.path.normcase(str(target.resolve()))
        except Exception:
            same = os.path.normcase(image) == os.path.normcase(str(target))
        if same:
            out.add(row["pid"])
    return out


def is_alive(pid: int) -> bool:
    """进程是否还在（用 SYNCHRONIZE 句柄等待 0 毫秒）。"""
    if not pid:
        return False
    handle = _process._open(int(pid), _process.SYNCHRONIZE)
    if not handle:
        return False
    try:
        return _kernel32.WaitForSingleObject(handle, 0) == _process.WAIT_TIMEOUT
    except Exception:
        return False
    finally:
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            pass
