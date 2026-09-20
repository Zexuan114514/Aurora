"""把「缺字版」补成完整台词：只读扫游戏进程内存，找包含它的那句话。

背景：WillPlus/AdvHD 这类引擎画字时走**字形缓存**，`GetGlyphOutlineW` 钩子只
在字形第一次出现时被调用，于是一句话会缺掉不少字（实测 少女之剑：
`家近離心倒` ← 真句 `家が近所で、年が離れていることもあって、…`）。

但缺字版的每个字都在真句里**按顺序**出现（是它的子序列），而真句此刻就躺在进程
内存里（脚本缓冲 / 文本框缓冲）。所以：读一遍可读内存 → 找「以缺字版为子序列」
的 UTF-16 串 → 取最紧凑、最像一句话的那个当完整台词。

全程**只读**（OpenProcess + ReadProcessMemory），不注入、不改内存、不挂钩子，
崩不了游戏；也不需要像 LunaHook 那样预先知道引擎里的函数地址。

实测（少女之剑，422 MB 内存）：全扫 5.2s，16 个候选里第 1 名就是真句；命中过
的区域会记成「热区」，之后每句只扫热区（毫秒级）。
"""
from __future__ import annotations

import ctypes
import difflib
import re
import threading
import time
from ctypes import wintypes

from aurora.infra import config

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
MAX_REGION_READ = 64 * 1024 * 1024


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD)]


kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                                    ctypes.c_size_t]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]

#: 「像一句日文」的字符：假名 / 汉字 / 全角标点
TEXT_RUN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f"
                         r"\u3000-\u303f\uff01-\uff60\u2015\u2026]{4,}")
_TRAILING_PUNCT = "。！？…‥」』）)!?、"
_LEADING_BRACKET = "「『（(【〈《"

_CACHE: dict[int, dict] = {}
_LOCK = threading.RLock()

#: 汉字 / 数字 / 拉丁字母（用来跳过注音假名再比对）
_IDEOGRAPH_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uff10-\uff19\uff21-\uff3a0-9A-Za-z]")


def kanji_span(probe: str, text: str) -> tuple[int, int] | None:
    """只比汉字/数字/字母的子序列匹配（跳过注音）。

    实测 AdvHD 画名字时会连**注音**一起画：`空木うつぎ日向ひなた…`。把假名两边都
    滤掉后剩下 `空木日向１年間留学本飛行中`，正好是真句 `オレ、空木日向は、…` 的
    子序列。返回匹配到的最小窗口（原串下标）。
    """
    probe_pos = [i for i, ch in enumerate(probe) if _IDEOGRAPH_RE.match(ch)]
    if len(probe_pos) < 4:
        return None
    text_pos = [j for j, ch in enumerate(text) if _IDEOGRAPH_RE.match(ch)]
    index = 0
    matched: list[int] = []
    for pos in text_pos:
        if index < len(probe_pos) and text[pos] == probe[probe_pos[index]]:
            matched.append(pos)
            index += 1
    if index < len(probe_pos):
        return None
    return (matched[0], matched[-1] + 1)


def _regions(handle) -> list[tuple[int, int]]:
    """进程里所有「已提交、可读、无 guard」的区域。"""
    out: list[tuple[int, int]] = []
    wow = wintypes.BOOL()
    kernel32.IsWow64Process(handle, ctypes.byref(wow))
    # 32 位（含 WOW64）目标只扫到 2GB；原生 64 位目标要扫到用户空间顶端
    top = 0x7FFF0000 if wow.value else 0x7FFFFFFF0000
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    while address < top:
        if not kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address),
                                       ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        size = int(mbi.RegionSize or 0x1000)
        if mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD) \
                and mbi.Protect != PAGE_NOACCESS:
            out.append((int(address), min(size, MAX_REGION_READ)))
        address += size
    return out


def window_span(probe: str, text: str) -> tuple[int, int] | None:
    """text 里「按顺序包含 probe」的最短窗口；找不到返回 None。

    最短窗口能把候选前后沾到的垃圾字符切掉（实测扫内存常拿到
    `蠀『男らしく…』って。` 这种，前面多一个字的版本）。
    """
    if not probe or not text or len(probe) > len(text):
        return None
    best: tuple[int, int] | None = None
    for start in range(len(text)):
        if text[start] != probe[0]:
            continue
        index = 1
        pos = start + 1
        while index < len(probe) and pos < len(text):
            if text[pos] == probe[index]:
                index += 1
            pos += 1
        if index == len(probe):
            span = (start, pos)
            if best is None or (span[1] - span[0]) < (best[1] - best[0]):
                best = span
                if span[1] - span[0] == len(probe):
                    break
    return best


def lcs_span(probe: str, text: str) -> tuple[tuple[int, int], float]:
    """最长公共子序列的覆盖位置与覆盖率。

    有的引擎画字时会把**注音（ルビ）**也一起画出来，残片会多出假名：
    实测 `空木うつぎ日向ひなた１年間留学え本へ飛行中` ← 真句
    `オレ、空木日向は、１年間の留学を終えて、日本へと向かう飛行機の中にいた。`。
    这种残片不是真句的子序列（多出来的假名卡在中间），但公共子序列覆盖率仍有 80%+，
    所以严格匹配找不到时再用这一条。返回 (窗口, 覆盖率)。
    """
    n, m = len(probe), len(text)
    if not n or not m:
        return (0, 0), 0.0
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        row, prev = table[i], table[i - 1]
        ch = probe[i - 1]
        for j in range(1, m + 1):
            row[j] = prev[j - 1] + 1 if ch == text[j - 1] else max(prev[j], row[j - 1])
    if not table[n][m]:
        return (0, 0), 0.0
    # 回溯出匹配位置 → 取最小窗口
    i, j = n, m
    first = last = -1
    while i > 0 and j > 0:
        if probe[i - 1] == text[j - 1]:
            first = j - 1
            if last < 0:
                last = j - 1
            i -= 1
            j -= 1
        elif table[i - 1][j] >= table[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return (first, last + 1), table[n][m] / n


def trim_sentence(text: str, span: tuple[int, int], *, left: int = 20,
                  right: int = 80) -> str:
    """把窗口补成一句完整的话。

    缺字版常常在句子中间就没了（`家近離心倒` ← `家が近所で、…面倒を見てもらっていた。`），
    所以右边要一直吃到句读；左边略微回退一点，别把句首的引号落下。
    """
    start, end = span
    limit = max(0, start - left)
    while start > limit and text[start - 1] not in "。！？!?…‥」』":
        start -= 1
    while end < len(text) and (end - start) < right:
        ch = text[end]
        end += 1
        if ch in _TRAILING_PUNCT:
            break
    return text[start:end].strip()


def _read_texts(handle, base: int, size: int):
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base), buffer, size,
                                      ctypes.byref(read)):
        return []
    try:
        data = buffer.raw[:read.value]
    except Exception:
        return []
    # UTF-16 串在区域里的起始位置可能是奇数 → 两种对齐都要看
    return [data.decode("utf-16-le", "ignore"),
            data[1:].decode("utf-16-le", "ignore")] if len(data) > 3 else []


def _scan(handle, regions, probe: str, *, max_len: int) -> tuple[dict[str, int], set[int]]:
    """返回 {窗口文本: 匹配等级}；等级 2=严格子序列、1=公共子序列、0=只比汉字。"""
    found: dict[str, int] = {}
    hot: set[int] = set()
    for base, size in regions:
        for text in _read_texts(handle, base, size):
            if not text:
                continue
            for match in TEXT_RUN_RE.finditer(text):
                candidate = match.group(0)
                if len(candidate) > max_len or len(candidate) <= len(probe):
                    continue
                span = window_span(probe, candidate)
                rank = 2
                if not span:
                    # 注音（ルビ）混进残片时严格子序列匹配会落空 → 退一步看公共子序列
                    loose, ratio = lcs_span(probe, candidate)
                    if ratio >= 0.7 and loose[1] > loose[0]:
                        span, rank = loose, 1
                    else:
                        span = kanji_span(probe, candidate)
                        rank = 0
                        if not span:
                            continue
                window = trim_sentence(candidate, span)
                if len(window) <= len(probe):
                    continue
                if found.get(window, -1) < rank:
                    found[window] = rank
                hot.add(base)
        if len(found) >= 40:
            break
    return found, hot


def candidates_ranked(pid: int, fragment: str, *, full: bool = False) -> dict[str, int]:
    """在进程内存里找候选句，返回 {窗口文本: 匹配等级}。"""
    probe = re.sub(r"\s+", "", str(fragment or ""))
    if not pid or len(probe) < 3:
        return {}
    with _LOCK:
        state = _CACHE.setdefault(pid, {"hot": set(), "regions": [], "at": 0.0})
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return {}                       # 权限不够（游戏以管理员跑）→ 安静地放弃
    try:
        if not state["regions"] or full:
            state["regions"] = _regions(handle)
            state["at"] = time.time()
        everything = state["regions"]
        hot_list = [row for row in everything if row[0] in state["hot"]] or everything
        max_len = max(80, len(probe) * 4 + 40)
        found, hot = _scan(handle, hot_list, probe, max_len=max_len)
        if not found and hot_list is not everything:
            found, hot = _scan(handle, everything, probe, max_len=max_len)
            state["at"] = time.time()
        if hot:
            state["hot"] |= hot
        return found
    finally:
        kernel32.CloseHandle(handle)


def candidates(pid: int, fragment: str, *, full: bool = False) -> list[str]:
    """候选句列表（按匹配等级排序，再按长度）。"""
    rows = candidates_ranked(pid, fragment, full=full)
    return sorted(rows, key=lambda text: (-rows[text], len(text)))


def _pick(pid: int, fragment: str, probe: str) -> tuple[str, tuple] | None:
    rows = candidates_ranked(pid, fragment)
    if not rows:
        return None
    scored: list[tuple[tuple, str]] = []
    for text, rank in rows.items():
        body = text.strip()
        if not body:
            continue
        cover = len(probe) / max(1, len(body))
        ends = bool(re.search(r"[。．！？!?…」』]$", body))
        starts = body[:1] == probe[:1] or (body[:1] in _LEADING_BRACKET
                                           and probe[1:2] in body[:3])
        scored.append(((ends, rank, starts, cover, -len(body)), body))
    if not scored:
        return None
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored[0][1], scored[0][0], scored  # type: ignore[return-value]


def complete(pid: int, fragment: str) -> str:
    """给出最可能的完整台词；拿不准就返回空串（宁可不补，也别补错）。

    判定偏保守：候选要么「唯一且以缺字版首字开头、以句读收尾」，要么明显领先
    第二名（覆盖率高 0.15 以上）。缺字版往往只覆盖真句的一小半，所以光看覆盖率
    会误判成「都不像」，这时靠「唯一性」兜住。
    """
    probe = re.sub(r"\s+", "", str(fragment or ""))
    picked = _pick(pid, fragment, probe)
    if not picked:
        return ""
    best, best_key, scored = picked
    if not best_key[0]:
        # 句子还没画完（引擎逐字写缓冲）→ 稍微等一下再扫一遍热区
        time.sleep(0.35)
        again = _pick(pid, fragment, probe)
        if again and (again[1][0] or len(again[0]) > len(best)):
            best, best_key, scored = again
    runner = scored[1][0] if len(scored) > 1 else None
    ends = best_key[0]
    cover = best_key[3]
    if runner and runner[0] and runner[1] == best_key[1]:
        # 第二名的形态一样好（也有句读、也是同一档匹配）→ 只有覆盖率明显领先才敢用
        if cover - runner[3] < 0.15 and (runner[4] - best_key[4]) < 4:
            return ""
    if not ends:
        return ""
    config.log(f"memmatch: {fragment[:20]!r} -> {best[:40]!r} "
               f"(候选 {len(scored)} 条, 等级 {best_key[1]})")
    return best


def reset(pid: int = 0) -> None:
    """换游戏/停翻译时清缓存（热区是按进程记的）。"""
    with _LOCK:
        if pid:
            _CACHE.pop(int(pid), None)
        else:
            _CACHE.clear()


# --------------------------------------------------------------------------- #
def _variants(probe: str) -> list[str]:
    """OCR 结果可能带着说话人名字/杂讯 → 多试几个「去掉开头一点」的版本。"""
    out = [probe]
    parts = probe.split(" ")
    if len(parts) > 1:
        out.append(" ".join(parts[1:]).strip())
        out.append(parts[-1].strip())
    for cut in (1, 2, 3, 4):
        if len(probe) > cut + 4:
            out.append(probe[cut:])
    return [row for row in dict.fromkeys(out) if len(row) >= 4]


def find_similar(pid: int, text: str, *, min_ratio: float = 0.6) -> list[tuple[float, str]]:
    """在进程内存里找「和这段文字最像」的句子（OCR 纠错用）。

    OCR 会把字认错（实测 アマカノ３：`強がりをうが` ← `強がりを言うけど`），
    但真句就在进程内存里，用相似度一比就能把错字纠回来。
    """
    probe = re.sub(r"\s+", "", str(text or ""))
    if not pid or len(probe) < 6:
        return []
    variants = _variants(probe)
    with _LOCK:
        state = _CACHE.setdefault(pid, {"hot": set(), "regions": [], "at": 0.0})
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return []
    found: dict[str, float] = {}

    def scan(regions) -> None:
        for base, size in regions:
            for decoded in _read_texts(handle, base, size):
                if not decoded:
                    continue
                for match in TEXT_RUN_RE.finditer(decoded):
                    candidate = match.group(0).strip()
                    if not (6 <= len(candidate) <= max(80, len(probe) * 2 + 20)):
                        continue
                    if not difflib.SequenceMatcher(None, probe, candidate).quick_ratio() \
                            >= min_ratio:
                        continue
                    best = 0.0
                    for variant in variants:
                        ratio = difflib.SequenceMatcher(None, variant, candidate).ratio()
                        best = max(best, ratio)
                    if best >= min_ratio and found.get(candidate, 0) < best:
                        found[candidate] = best
                if len(found) >= 60:
                    return
        return

    try:
        if not state["regions"]:
            state["regions"] = _regions(handle)
            state["at"] = time.time()
        hot = [row for row in state["regions"] if row[0] in state["hot"]]
        if hot:
            scan(hot)
        if not found and len(hot) != len(state["regions"]):
            scan(state["regions"])
        return sorted(((ratio, text_row) for text_row, ratio in found.items()),
                      key=lambda row: -row[0])
    finally:
        kernel32.CloseHandle(handle)


def snap(pid: int, text: str, *, min_ratio: float = 0.72, margin: float = 0.08) -> str:
    """把 OCR 文本吸附到内存里的原文；不确定就原样返回空串。"""
    rows = find_similar(pid, text)
    if not rows:
        return ""
    best_ratio, best = rows[0]
    if best_ratio < min_ratio:
        return ""
    runner = rows[1][0] if len(rows) > 1 else 0.0
    if runner and best_ratio - runner < margin:
        return ""                       # 两个候选太接近 → 不敢替换
    probe = re.sub(r"\s+", "", str(text or ""))
    if re.sub(r"\s+", "", best) == probe:
        return ""                       # 和 OCR 一样，不用动
    config.log(f"memmatch snap: {text[:26]!r} -> {best[:40]!r} ({best_ratio:.2f})")
    return best
