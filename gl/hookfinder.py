"""自研「钩子查找器」：没有现成钩子时，自己把那条钩子找出来。

思路（看 MisakaHookFinder / Textractor 的 hookfinder 学来的方法，代码自己写）：
  1. 先知道**当前这句台词**是什么（OCR 得到，或用户手填）；
  2. 在游戏进程内存里定位这段文本的缓冲区地址；
  3. 以**调试器**身份附加，给所有线程布**硬件数据断点**盯住那几个地址；
  4. 游戏再访问这句文本时 CPU 会报单步异常 → 拿到「访问它的那条指令(RIP)」与
     「当时的栈指针(ESP)」；
  5. 在栈上找哪个槽正好等于那个缓冲区地址 → 这就是 H-code 的 `data_offset`；
     指令地址就是 hook 地址；缓冲区编码决定用 `Q`(UTF-16) 还是 `S`+`65001#`(UTF-8)。

和 Textractor/Misaka 的做法相比：**不批量挂钩**（他们要把几千个地址全挂上再让玩家点，
所以游戏会卡/闪），我们只盯当前这句文本的缓冲区，靠硬件断点精确抓那一条指令。
代价：文本只经寄存器传递、栈上完全不留痕的情况抓不到（那就只能 OCR）。
"""
from __future__ import annotations

import ctypes
import difflib
import os
import re
import zlib
import threading
import time
from ctypes import wintypes

from . import config, memmatch

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

THREAD_SUSPEND_RESUME = 0x0002
THREAD_GET_CONTEXT = 0x0008
THREAD_SET_CONTEXT = 0x0010
TH32CS_SNAPTHREAD = 0x00000004

CONTEXT_AMD64 = 0x00100000
CONTEXT_i386 = 0x00010000
CONTEXT_ALL_x64 = CONTEXT_AMD64 | 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008 \
    | 0x00000010
CONTEXT_ALL_x86 = CONTEXT_i386 | 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008 \
    | 0x00000010

DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_DEBUG_EVENT = 1
EXCEPTION_SINGLE_STEP = 0x80000004
CREATE_THREAD_DEBUG_EVENT = 2
EXIT_PROCESS_DEBUG_EVENT = 5

STACK_SCAN_BACK = 0x100        # 断点处往前扫多少字节栈
STACK_SCAN_FORWARD = 0x100     # 往后扫多少（调用者的参数在这一侧）
MAX_HITS = 24
MAX_BUFFER_K = 8               # 栈槽指向「缓冲区+k」时用 padding 表达


class HookFinderError(RuntimeError):
    """带机器可读原因的错误（界面按 reason 给不同文案）。"""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                ("dwFlags", wintypes.DWORD)]


class DEBUG_EVENT(ctypes.Structure):
    """只按前 4 个字段 + 一段原始 union 取用，避免 x86/x64 结构差异踩坑。"""

    _fields_ = [("dwDebugEventCode", wintypes.DWORD), ("dwProcessId", wintypes.DWORD),
                ("dwThreadId", wintypes.DWORD), ("_pad", wintypes.DWORD),
                ("u", ctypes.c_ubyte * 176)]


kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.DebugActiveProcess.argtypes = [wintypes.DWORD]
kernel32.DebugActiveProcessStop.argtypes = [wintypes.DWORD]
kernel32.DebugSetProcessKillOnExit.argtypes = [wintypes.BOOL]
kernel32.WaitForDebugEvent.argtypes = [ctypes.POINTER(DEBUG_EVENT), wintypes.DWORD]
kernel32.ContinueDebugEvent.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenThread.restype = wintypes.HANDLE
kernel32.SuspendThread.argtypes = [wintypes.HANDLE]
kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
kernel32.GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Wow64GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Wow64SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]


def _is_wow64(handle) -> bool:
    wow = wintypes.BOOL()
    try:
        if kernel32.IsWow64Process(handle, ctypes.byref(wow)):
            return bool(wow.value)
    except Exception:
        pass
    return False


def _thread_ids(pid: int) -> list[int]:
    out: list[int] = []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snap:
        return out
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        more = kernel32.Thread32First(snap, ctypes.byref(entry))
        while more:
            if int(entry.th32OwnerProcessID) == int(pid):
                out.append(int(entry.th32ThreadID))
            more = kernel32.Thread32Next(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


def _read_raw(handle, address: int, size: int) -> bytes:
    if size <= 0 or not address:
        return b""
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size,
                                      ctypes.byref(read)):
        return b""
    return buffer.raw[:read.value]


ENCODINGS = (("utf-16", "utf-16-le"), ("utf-8", "utf-8"), ("sjis", "cp932"))


def locate_buffers(pid: int, text: str, *, limit: int = 8,
                   fuzzy: float = 0.8, allow_fuzzy: bool = True) -> list[dict]:
    """在进程内存里定位这段文本的缓冲区（精确优先；模糊档很慢，默认给手动场景用）。

    实测 アマカノ３ 这类引擎的台词是**渲染时临时生成**的，内存里往往查不到逐字副本
    —— 所以 App 里走「差分法」（见 snapshot/changed_dialogues），这里 allow_fuzzy=False。
    """
    body = " ".join(str(text or "").split())
    if len(body) < 2:
        return []
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise HookFinderError("no-access",
                              f"读不了游戏内存（权限不足？）err={ctypes.get_last_error()}")
    found: list[dict] = []
    seen: set[int] = set()
    try:
        regions = memmatch._regions(handle)
        needles = []
        for label, codec in ENCODINGS:
            try:
                raw = body.encode(codec)
            except Exception:
                continue
            if len(raw) >= 4:
                needles.append((label, raw))
        for base, size in regions:
            data = _read_raw(handle, base, size)
            if not data:
                continue
            for label, needle in needles:
                start = 0
                while len(found) < limit * 4:
                    offset = data.find(needle, start)
                    if offset < 0:
                        break
                    address = base + offset
                    if address not in seen:
                        seen.add(address)
                        found.append({"address": address, "encoding": label,
                                      "exact": True})
                    start = offset + 1
            if len(found) >= limit * 4:
                break
        if not found and allow_fuzzy:
            found = _locate_fuzzy(handle, regions, body, limit, fuzzy)
    finally:
        kernel32.CloseHandle(handle)
    found.sort(key=lambda row: (not row["exact"],
                                0 if row["encoding"] == "utf-16" else 1))
    return found[:limit]


def _locate_fuzzy(handle, regions, body: str, limit: int, min_ratio: float) -> list[dict]:
    """精确找不到时的兜底：OCR 常把台词认错（还可能把名字框一起认进来），
    所以用「子序列 / 公共子序列 / 只比汉字 / 相似度」几档一起上，并且多试几个
    「掐掉开头一点」的变体。"""
    out: list[dict] = []
    probes = memmatch._variants(body)
    for base, size in regions:
        data = _read_raw(handle, base, size)
        if not data:
            continue
        decoded = data.decode("utf-16-le", "ignore")
        for match in memmatch.TEXT_RUN_RE.finditer(decoded):
            run = match.group(0)
            if len(run) < 4 or abs(len(run) - len(body)) > max(16, len(body)):
                continue
            hit = False
            for probe in probes:
                if memmatch.window_span(probe, run):
                    hit = True
                    break
                if memmatch.kanji_span(probe, run):
                    hit = True
                    break
                _span, ratio = memmatch.lcs_span(probe, run)
                if ratio >= 0.7:
                    hit = True
                    break
                if difflib.SequenceMatcher(None, probe, run).ratio() >= min_ratio:
                    hit = True
                    break
            if not hit:
                continue
            try:
                needle = run.encode("utf-16-le")
            except Exception:
                continue
            offset = data.find(needle)
            if offset >= 0:
                out.append({"address": base + offset, "encoding": "utf-16",
                            "exact": False})
        if len(out) >= limit:
            break
    return out


def build_code(*, module: str, module_base: int, rip: int, offset: int,
               padding: int = 0, encoding: str = "utf-16") -> str:
    """按 Textractor 的 H-code 语法拼码。

    关键坑（用用户实测的 アマカノ３ 码校准过）：Textractor **解析** H-code 时，对负的
    data_offset 会再 `-= 4`（源码 host/hookcode.cpp 那句 ITH 兼容），所以我们实测到的
    真实栈偏移 `o<0` 必须写成 `-(|o|+4)` 才能被它读回同一个槽：
        真实 -0x70 → 写 -6C（= 用户搜到的 `HS65001#-6C@1401B1F70`）。
    """
    rva = int(rip) - int(module_base)
    if rva < 0:
        raise HookFinderError("bad-address", "指令地址不在模块内")
    mode = "Q" if encoding == "utf-16" else "S"
    page = "" if encoding == "utf-16" else ("65001#" if encoding == "utf-8" else "")
    emit = int(offset)
    if emit < 0:
        emit += 4
    sign = "-" if emit < 0 else ""
    pad = f"{int(padding):X}+" if padding else ""
    return f"H{mode}{page}{pad}{sign}{abs(emit):X}@{rva:X}:{module}"


class CONTEXT64(ctypes.Structure):
    """x64 CONTEXT（只到 Rip，尾部按真实大小补齐）。

    踩过的坑：不能拿 `create_string_buffer` + `c_void_p` 传给 GetThreadContext ——
    内核会「调用成功但什么都不写」。必须传一个真正的 CONTEXT 结构体指针。
    """

    _fields_ = [("P1Home", ctypes.c_uint64), ("P2Home", ctypes.c_uint64),
                ("P3Home", ctypes.c_uint64), ("P4Home", ctypes.c_uint64),
                ("P5Home", ctypes.c_uint64), ("P6Home", ctypes.c_uint64),
                ("ContextFlags", wintypes.DWORD), ("MxCsr", wintypes.DWORD),
                ("SegCs", wintypes.WORD), ("SegDs", wintypes.WORD),
                ("SegEs", wintypes.WORD), ("SegFs", wintypes.WORD),
                ("SegGs", wintypes.WORD), ("SegSs", wintypes.WORD),
                ("EFlags", wintypes.DWORD),
                ("Dr0", ctypes.c_uint64), ("Dr1", ctypes.c_uint64),
                ("Dr2", ctypes.c_uint64), ("Dr3", ctypes.c_uint64),
                ("Dr6", ctypes.c_uint64), ("Dr7", ctypes.c_uint64),
                ("Rax", ctypes.c_uint64), ("Rcx", ctypes.c_uint64),
                ("Rdx", ctypes.c_uint64), ("Rbx", ctypes.c_uint64),
                ("Rsp", ctypes.c_uint64), ("Rbp", ctypes.c_uint64),
                ("Rsi", ctypes.c_uint64), ("Rdi", ctypes.c_uint64),
                ("R8", ctypes.c_uint64), ("R9", ctypes.c_uint64),
                ("R10", ctypes.c_uint64), ("R11", ctypes.c_uint64),
                ("R12", ctypes.c_uint64), ("R13", ctypes.c_uint64),
                ("R14", ctypes.c_uint64), ("R15", ctypes.c_uint64),
                ("Rip", ctypes.c_uint64),
                ("tail", ctypes.c_ubyte * (1232 - 256))]


class CONTEXT32(ctypes.Structure):
    """x86 / WOW64 的 CONTEXT（Eip=184、Esp=196）。"""

    _fields_ = [("ContextFlags", wintypes.DWORD),
                ("Dr0", wintypes.DWORD), ("Dr1", wintypes.DWORD),
                ("Dr2", wintypes.DWORD), ("Dr3", wintypes.DWORD),
                ("Dr6", wintypes.DWORD), ("Dr7", wintypes.DWORD),
                ("FloatSave", ctypes.c_ubyte * 112),
                ("SegGs", wintypes.DWORD), ("SegFs", wintypes.DWORD),
                ("SegEs", wintypes.DWORD), ("SegDs", wintypes.DWORD),
                ("Edi", wintypes.DWORD), ("Esi", wintypes.DWORD),
                ("Ebx", wintypes.DWORD), ("Edx", wintypes.DWORD),
                ("Ecx", wintypes.DWORD), ("Eax", wintypes.DWORD),
                ("Ebp", wintypes.DWORD), ("Eip", wintypes.DWORD),
                ("SegCs", wintypes.DWORD), ("EFlags", wintypes.DWORD),
                ("Esp", wintypes.DWORD), ("SegSs", wintypes.DWORD),
                ("ExtendedRegisters", ctypes.c_ubyte * 512)]


kernel32.GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Wow64GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
kernel32.Wow64SetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]


class _Context:
    """读写线程上下文的 DRx / RIP / ESP（x64 原生 与 WOW64 两套布局）。"""

    def __init__(self, tid: int, wow: bool) -> None:
        self.tid = tid
        self.wow = wow
        self.step = 4 if wow else 8
        self.klass = CONTEXT32 if wow else CONTEXT64
        self.handle = kernel32.OpenThread(
            THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_SET_CONTEXT, False, tid)

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = 0

    def _getter(self):
        return kernel32.Wow64GetThreadContext if self.wow else kernel32.GetThreadContext

    def _setter(self):
        return kernel32.Wow64SetThreadContext if self.wow else kernel32.SetThreadContext

    def _fresh(self):
        ctx = self.klass()
        flags = CONTEXT_ALL_x86 if self.wow else CONTEXT_ALL_x64
        ctx.ContextFlags = flags
        return ctx

    def get(self) -> dict | None:
        if not self.handle:
            return None
        ctx = self._fresh()
        if not self._getter()(self.handle, ctypes.byref(ctx)):
            return None
        return {"sp": int(ctx.Esp if self.wow else ctx.Rsp),
                "ip": int(ctx.Eip if self.wow else ctx.Rip),
                "dr0": int(ctx.Dr0), "dr1": int(ctx.Dr1), "dr2": int(ctx.Dr2),
                "dr3": int(ctx.Dr3), "dr6": int(ctx.Dr6), "dr7": int(ctx.Dr7),
                "wow": self.wow}

    def set(self, *, dr0: int | None = None, dr1: int | None = None,
            dr2: int | None = None, dr3: int | None = None, dr7: int | None = None,
            clear_dr6: bool = False) -> bool:
        if not self.handle:
            return False
        ctx = self._fresh()
        if not self._getter()(self.handle, ctypes.byref(ctx)):
            return False
        for name, value in (("Dr0", dr0), ("Dr1", dr1), ("Dr2", dr2), ("Dr3", dr3)):
            if value is not None:
                setattr(ctx, name, int(value))
        if dr7 is not None:
            ctx.Dr7 = int(dr7)
        if clear_dr6:
            ctx.Dr6 = 0
        return bool(self._setter()(self.handle, ctypes.byref(ctx)))


def _dr7_for(count: int) -> int:
    """给前 count 个槽配「读写、长度 1 字节」的数据断点（1 字节没有对齐要求）。"""
    value = 0
    for index in range(count):
        value |= 1 << (index * 2)              # Ln
        value |= 0b11 << (16 + index * 4)      # RWn = 读/写
        value |= 0b00 << (18 + index * 4)      # LENn = 1 字节
    return value


def _collect_hit(handle, state: dict, targets: list[dict]) -> dict | None:
    """在断点处扫栈：找出哪个槽指着我们的缓冲区。"""
    sp, ip = int(state["sp"]), int(state["ip"])
    step = 4 if state.get("wow") else 8
    start = sp - STACK_SCAN_BACK
    data = _read_raw(handle, start, STACK_SCAN_BACK + STACK_SCAN_FORWARD)
    if not data:
        return None
    for index in range(0, len(data) - step + 1, step):
        value = int.from_bytes(data[index:index + step], "little")
        for target in targets:
            delta = value - int(target["address"])
            if 0 <= delta < MAX_BUFFER_K:
                return {"rip": ip, "offset": start + index - sp, "padding": delta,
                        "buffer": int(target["address"]),
                        "encoding": str(target.get("encoding") or "utf-16")}
    return None


def search(pid: int, buffers: list[dict], *, seconds: float = 8.0,
           stop_event: threading.Event | None = None,
           on_hit=None) -> dict:
    """布断点、等游戏访问这几段文本，收集候选（返回 {"ok", "hits", "reason"}）。"""
    targets = [dict(row) for row in buffers][:4]
    if not targets:
        return {"ok": False, "reason": "no-buffer", "hits": []}
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE
        | PROCESS_VM_OPERATION, False, pid)
    if not handle:
        return {"ok": False, "reason": "no-access", "hits": []}
    wow = _is_wow64(handle)
    try:
        kernel32.DebugSetProcessKillOnExit(False)   # 我们退出时别把游戏带走
        if not kernel32.DebugActiveProcess(pid):
            kernel32.CloseHandle(handle)
            return {"ok": False, "reason": "attach-failed",
                    "error": ctypes.get_last_error(), "hits": []}
    except Exception as exc:
        kernel32.CloseHandle(handle)
        return {"ok": False, "reason": "attach-failed", "error": str(exc), "hits": []}

    armed: dict[int, _Context] = {}
    hits: dict[tuple, dict] = {}
    steps = 0
    armed_threads = 0
    events: dict[int, int] = {}
    deadline = time.time() + max(1.0, float(seconds))
    attached = True

    def arm(tid: int) -> None:
        if tid in armed:
            return
        ctx = _Context(tid, wow)
        if not ctx.handle:
            return
        kernel32.SuspendThread(ctx.handle)
        ok = ctx.set(dr0=targets[0]["address"],
                     dr1=targets[1]["address"] if len(targets) > 1 else None,
                     dr2=targets[2]["address"] if len(targets) > 2 else None,
                     dr3=targets[3]["address"] if len(targets) > 3 else None,
                     dr7=_dr7_for(len(targets)), clear_dr6=True)
        kernel32.ResumeThread(ctx.handle)
        if ok:
            armed[tid] = ctx
        else:
            ctx.close()

    def disarm() -> None:
        for ctx in list(armed.values()):
            try:
                kernel32.SuspendThread(ctx.handle)
                ctx.set(dr0=0, dr1=0, dr2=0, dr3=0, dr7=0, clear_dr6=True)
                kernel32.ResumeThread(ctx.handle)
            except Exception:
                pass
            ctx.close()
        armed.clear()

    try:
        # 注意顺序（踩过坑）：必须在**调试事件放行之后**再挂断点 —— 在事件处理期间改
        # 线程上下文，ContinueDebugEvent 会被系统保存的上下文覆盖，断点等于白挂。
        # 所以先跑起来，等首个断点事件放行后统一布点；新线程同理延后一拍。
        pending = set(_thread_ids(pid))
        event = DEBUG_EVENT()
        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                break
            if pending:
                for tid in list(pending):
                    arm(tid)
                    pending.discard(tid)
                armed_threads = len(armed)
            if not kernel32.WaitForDebugEvent(ctypes.byref(event), 120):
                continue
            code = int(event.dwDebugEventCode)
            tid = int(event.dwThreadId)
            events[code] = events.get(code, 0) + 1
            cont = DBG_CONTINUE
            if code == EXCEPTION_DEBUG_EVENT:
                exc_code = int.from_bytes(bytes(event.u[0:4]), "little")
                if exc_code == EXCEPTION_SINGLE_STEP:
                    ctx = armed.get(tid)
                    if ctx is None:
                        arm(tid)
                        ctx = armed.get(tid)
                    state = ctx.get() if ctx else None
                    if state and (state["dr6"] & 0xF):
                        steps += 1
                        hit = _collect_hit(handle, state, targets)
                        if hit:
                            key = (hit["rip"], hit["offset"], hit["padding"])
                            row = hits.setdefault(key, {**hit, "count": 0})
                            row["count"] += 1
                            if on_hit:
                                try:
                                    on_hit(dict(row))
                                except Exception:
                                    pass
                        if ctx:
                            ctx.set(clear_dr6=True)
                elif exc_code == 0x80000003:
                    # 附加时系统会在调试对象里插一个 int3；这是我们自己的事件，放行即可
                    pending.update(_thread_ids(pid))
                else:
                    cont = DBG_EXCEPTION_NOT_HANDLED
            elif code == CREATE_THREAD_DEBUG_EVENT:
                pending.add(tid)
            elif code == EXIT_PROCESS_DEBUG_EVENT:
                kernel32.ContinueDebugEvent(int(event.dwProcessId), tid, cont)
                attached = False
                break
            kernel32.ContinueDebugEvent(int(event.dwProcessId), tid, cont)
    finally:
        disarm()
        if attached:
            try:
                kernel32.DebugActiveProcessStop(pid)
            except Exception:
                pass
        kernel32.CloseHandle(handle)
    rows = sorted(hits.values(), key=lambda row: -row["count"])
    config.log(f"hookfinder: pid={pid} 盯了 {len(targets)} 段文本、布点线程 {armed_threads} 个，"
               f"断点触发 {steps} 次，命中 {len(rows)} 条候选，调试事件 {events}")
    return {"ok": bool(rows), "hits": rows[:MAX_HITS],
            "steps": steps, "armed_threads": armed_threads, "events": dict(events),
            "reason": "" if rows else ("no-hit" if steps else "no-break")}


# --------------------------------------------------------------------------- #
# 差分法：台词往往是渲染时临时生成的（内存里查不到逐字副本），所以改「盯变化」
# --------------------------------------------------------------------------- #

def _text_at(handle, address: int, limit: int = 0) -> tuple[str, str]:
    """读一段内存并判定它是哪种编码的文本（P3.9：UTF-8/UTF-16 双解码择优）。"""
    size = int(limit or 256)
    raw = _read_raw(handle, int(address), size)
    if len(raw) < 4:
        return "", ""
    text, encoding = choose_decoding(raw)
    if len(text) < 2:
        return "", ""
    return text, encoding


def harvest(pid: int, *, seconds: float = 12.0, stop_event=None,
            on_progress=None) -> list[dict]:
    """采样式收集候选（Misaka「翻页数次后列出所有候选」的思路，但不挂钩子）。

    做法：高频采样每个线程的栈 —— 每次拿到 ESP，扫 [ESP-0x100, ESP+0x100] 的槽；
    凡是槽值指向一段「日文台词」的，就把 **(该帧返回地址, 槽相对 ESP 的偏移, 文本)**
    记成一条候选（同一组按出现次数累加）。

    好处：不用附加调试器、不挂钩子、不批量改代码；而且**文本我们已经直接读到**，
    所以「哪条候选吐出来的才是原文」可以和当前 OCR 到的台词一比就自动判定。
    """
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise HookFinderError("no-access", "读不了游戏内存（权限不足？）")
    wow = _is_wow64(handle)
    rows: dict[tuple, dict] = {}
    started = time.time()
    samples = 0
    try:
        while time.time() - started < max(1.0, float(seconds)):
            if stop_event is not None and stop_event.is_set():
                break
            for tid in _thread_ids(pid):
                if stop_event is not None and stop_event.is_set():
                    break
                ctx = _Context(tid, wow)
                if not ctx.handle:
                    continue
                kernel32.SuspendThread(ctx.handle)
                state = ctx.get()
                kernel32.ResumeThread(ctx.handle)
                ctx.close()
                if not state:
                    continue
                samples += 1
                sp = int(state["sp"])
                step = 4 if wow else 8
                data = _read_raw(handle, sp - STACK_SCAN_BACK,
                                 STACK_SCAN_BACK + STACK_SCAN_FORWARD)
                if len(data) < step * 4:
                    continue
                ret = int.from_bytes(data[STACK_SCAN_BACK:STACK_SCAN_BACK + step],
                                     "little")
                for index in range(0, len(data) - step + 1, step):
                    slot_addr = sp - STACK_SCAN_BACK + index
                    value = int.from_bytes(data[index:index + step], "little")
                    if not value or value == slot_addr:
                        continue
                    text, encoding = _text_at(handle, value)
                    if not text:
                        # 不像文本但像代码地址 → 这是「下一层帧」的返回地址；
                        # 旧实现把 ±0x100 里所有槽都算到 [sp] 那一帧，导致 rip 指错位置，
                        # 拼出的 H-code 自然挂不到真正读文本的那条指令上。
                        if 0x10000 <= value < 0x7FFF_FFFF_FFFF:
                            ret = value
                        continue
                    key = (ret, slot_addr - sp, encoding)
                    row = rows.setdefault(key, {"rip": ret, "offset": slot_addr - sp,
                                                "padding": 0, "encoding": encoding,
                                                "text": text, "count": 0})
                    row["count"] += 1
                    if len(text) > len(row["text"]):
                        row["text"] = text
            if on_progress:
                try:
                    on_progress(len(rows), samples)
                except Exception:
                    pass
            time.sleep(0.05)
    finally:
        kernel32.CloseHandle(handle)
    out = sorted(rows.values(), key=lambda row: -row["count"])
    config.log(f"hookfinder harvest: 采样 {samples} 次，候选 {len(out)} 条")
    return out[:40]


DIALOGUE_HINT_RE = re.compile(r"[\u3040-\u30ff]")       # 有假名才像台词


def snapshot(pid: int) -> dict[int, int]:
    """给可写内存拍一张「区域 → CRC32」快照（1GB 内存约 1 秒）。"""
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise HookFinderError("no-access", "读不了游戏内存")
    out: dict[int, int] = {}
    try:
        for base, size in memmatch._regions(handle):
            data = _read_raw(handle, base, size)
            if data:
                out[base] = zlib.crc32(data)
    finally:
        kernel32.CloseHandle(handle)
    return out


def changed_dialogues(pid: int, before: dict[int, int], *, limit: int = 8,
                      min_chars: int = 6) -> list[dict]:
    """找出「变了的内存区域」里新出现的台词串（UTF-16 / UTF-8 / Shift-JIS）。"""
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise HookFinderError("no-access", "读不了游戏内存")
    out: list[dict] = []
    seen: set[int] = set()
    try:
        regions = memmatch._regions(handle)
        for base, size in regions:
            data = _read_raw(handle, base, size)
            if not data:
                continue
            if before.get(base) == zlib.crc32(data):
                continue                      # 这段没变，跳过
            for label, codec in (("utf-16", "utf-16-le"), ("utf-8", "utf-8"),
                                 ("sjis", "cp932")):
                out.extend(_dialogues_in(data, base, label, codec, min_chars))
            out = [row for row in out if row["address"] not in seen
                   or seen.add(row["address"]) is None]
            if len(out) >= limit * 4:
                break
    finally:
        kernel32.CloseHandle(handle)
    # 显示用的那句通常**短**（脚本缓冲里是长串），所以短句优先，且别要超长的
    rows = [row for row in out if len(row["text"]) <= 160]
    rows.sort(key=lambda row: len(row["text"]))
    out = rows or out
    out.sort(key=lambda row: len(row["text"]))
    return out[:limit]


def _dialogues_in(data: bytes, base: int, label: str, codec: str,
                  min_chars: int) -> list[dict]:
    out: list[dict] = []
    try:
        decoded = data.decode(codec, "ignore")
    except Exception:
        return out
    for match in memmatch.TEXT_RUN_RE.finditer(decoded):
        run = match.group(0).strip()
        if len(run) < min_chars or not DIALOGUE_HINT_RE.search(run):
            continue
        if re.search(r"[\u0400-\u04ff\u0530-\u058f\u0590-\u05ff\u0900-\u097f]", run):
            continue                          # 混进西里尔/希伯来等 → 乱码
        try:
            needle = run.encode(codec)
        except Exception:
            continue
        offset = data.find(needle)
        if offset >= 0:
            out.append({"address": base + offset, "encoding": label,
                        "exact": False, "text": run})
    return out


def module_of(pid: int, address: int) -> tuple[str, int]:
    """地址属于哪个模块 → (文件名, 模块基址)；拿不到返回 ("", 0)。"""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                               wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD)]
    kernel32.K32EnumProcessModules.restype = wintypes.BOOL
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                           ctypes.c_wchar_p, wintypes.DWORD]
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return "", 0
    try:
        needed = wintypes.DWORD()
        modules = (ctypes.c_void_p * 512)()
        if not kernel32.K32EnumProcessModules(handle, ctypes.byref(modules),
                                              ctypes.sizeof(modules),
                                              ctypes.byref(needed)):
            return "", 0
        count = min(len(modules), needed.value // ctypes.sizeof(ctypes.c_void_p))
        best = ("", 0)
        for index in range(count):
            base = int(modules[index] or 0)
            if not base or base > int(address) or base <= best[1]:
                continue
            buffer = ctypes.create_unicode_buffer(1024)
            if not psapi.GetModuleFileNameExW(handle, modules[index], buffer, 1024):
                continue
            best = (os.path.basename(buffer.value), base)
        return best
    finally:
        kernel32.CloseHandle(handle)

def choose_decoding(raw: bytes) -> tuple[str, str]:
    """把一段内存按 UTF-8 / UTF-16 各解一次，返回（文本, 编码），取更像台词的那个。

    真机教训（アマカノ３ / Artemis-Emote）：这类引擎的文本是 UTF-8，旧实现只按 UTF-16 解，
    读出来是「罕见汉字 + 零散片假名」的乱码（圠荈レ譈䣲骍Ｘ），既骗过重复检测又让候选全废。
    打分用 domain 层的 hook_candidate_score（纯函数，无 IO），保证与找钩子的排序口径一致。
    """
    from aurora.domain.text_rules import hook_candidate_score
    best_text, best_enc, best_score = "", "", -1.0
    for encoding, codec in (("utf-8", "utf-8"), ("utf-16", "utf-16-le")):
        try:
            text = raw.decode(codec, "ignore")
        except Exception:
            continue
        text = text.replace("\x00", "").strip()
        if not text:
            continue
        score = hook_candidate_score(text)
        if score > best_score:
            best_text, best_enc, best_score = text, encoding, score
    return best_text, best_enc
