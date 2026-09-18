"""游戏内文本来源：TextractorCLI 文本钩子 + 屏幕 OCR 兜底。

TextractorCLI 的契约（读它的 host/CLI/main.cpp 得出）：
  stdin  ：UTF-16LE 命令，`attach -P<pid>` / `detach -P<pid>` / `<hook码> -P<pid>`
  stdout ：UTF-16LE 行，格式 `[handle:pid:addr:ctx:ctx2:线程名:hook码] 正文`
我们只运行用户自己安装的 TextractorCLI.exe，不打包、不修改它。
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config, screencap

CREATE_NO_WINDOW = 0x08000000
CLI_NAME = "TextractorCLI.exe"
TEXTRACTOR_URL = "https://github.com/Artikash/Textractor/releases"

#: 钩子文本里常见的菜单/系统提示，翻译它们只会干扰阅读
NOISE_WORDS = ("无法注入", "Usage:", "Textractor:", "请以管理员", "注入失败","設定", "セーブ", "ロード", "タイトル", "終了", "バックログ", "スキップ",
               "オプション", "コンフィグ", "ウィンドウ", "フルスクリーン", "音量", "戻る",
               "はじめから", "つづきから", "終わります", "よろしいですか",
               # Textractor 自己的状态行（实测会被当台词送去翻译）
               "vnreng", "hijacking", "注入钩子", "管道已连接", "INSERT ", "disable GDI hooks",
               "已连接", "successfully attached")

#: 折叠「连续重复字符」时要放过的字符：这些连写本身有意义（「！！」「……」），
#: 折掉会改坏原文。注意「「「」这种引号连写一定是写缓冲痕迹，不能放过。
KEEP_RUN_CHARS = set("。、，．,.！？!?…‥ー〜～゛゜")

#: 引擎识别特征（按进程加载的模块名判断；这些都是我们自己观察到的模块名，
#: 不复制 Textractor / LunaHook 的引擎表或钩子码数据）
ENGINE_SIGNATURES = (
    ("TVP/KIRIKIRI", ("tvp(kirikiri)", "kirikiri", "krkr", "tvp_", "krkrz")),
    ("WillPlus", ("willplus", "advhd", "will_", "wpm")),
    ("BGI/Ethornell", ("bgi", "ethornell", "buriko")),
    ("Artemis/Siglus", ("siglus", "artemis", "ave;new")),
)

#: 钩子输出里的引擎特征。实测：游戏模块名里看不出来的引擎（DRACU RIOT 进程里
#: 没有任何 kirikiri 字样的模块），Textractor 自己的状态行会写明
#: 「vnreng: INSERT KiriKiriZ」——这条信息比模块名可靠。
HOOK_ENGINE_HINTS = (
    # 注意：这里**不能**放 "vnreng" —— Leaf / Escu:de 也会打 `vnreng:` 前缀，
    # 那样所有引擎都会被认成 KiriKiri（实测踩过）
    ("TVP/KIRIKIRI", ("kirikiriz", "kirikiri", "tvp(kirikiri)")),
    ("WillPlus", ("willplus", "advhd", "embedwillplus")),
    ("BGI/Ethornell", ("ethornell", "buriko", "bgimt")),
    ("Artemis/Siglus", ("siglus", "artemis")),
    ("Leaf", ("leafloader", "leafengine")),      # 只用长词，免得英文里的 "leaf" 误判
    ("Escu:de", ("escude",)),
    ("CatSystem2/Ares", ("catsystem", "cs2", "ares")),
    ("Majiro", ("majiro",)),
    ("Malie", ("malie",)),
    ("YU-RIS", ("yuris",)),
    ("RUGP", ("rugp",)),
    ("NeXAS", ("nexas",)),
    ("Nitroplus", ("nitroplus",)),
    ("AliceSoft", ("alicesoft", "system4")),
    ("Eushully", ("eushully",)),
    ("Renpy", ("renpy", "ren'py")),
    ("NScripter", ("nscripter", "onscripter", "ponscripter")),
    ("Siglus", ("siglusengine",)),
)

#: `vnreng: INSERT xxx` 里的引擎名 → 我们自己的名字。Textractor 注入成功时会打印
#: 这一行，比关键词猜测准得多（实测「INSERT Leaf」曾被错认成 TVP/KIRIKIRI）。
INSERT_ENGINE_NAMES = {
    "kirikiriz": "TVP/KIRIKIRI", "kirikiri": "TVP/KIRIKIRI", "kirikiriz2": "TVP/KIRIKIRI",
    "tvp": "TVP/KIRIKIRI", "krkrz": "TVP/KIRIKIRI",
    "leaf": "Leaf", "leafloader": "Leaf",
    "escude": "Escu:de",
    "willplus": "WillPlus", "willplusw": "WillPlus", "willplusa": "WillPlus",
    "willplus2": "WillPlus", "willplus3": "WillPlus", "embedwillplus": "WillPlus",
    "ethornell": "BGI/Ethornell", "bgi": "BGI/Ethornell", "buriko": "BGI/Ethornell",
    "siglus": "Siglus", "siglusengine": "Siglus", "artemis": "Artemis/Siglus",
    "catsystem2": "CatSystem2/Ares", "catsystem": "CatSystem2/Ares",
    "majiro": "Majiro", "malie": "Malie", "yuris": "YU-RIS", "rugp": "RUGP",
    "nexas": "NeXAS", "nitroplus": "Nitroplus", "alice": "AliceSoft",
    "system4": "AliceSoft", "eushully": "Eushully", "renpy": "Renpy",
    "nscripter": "NScripter", "ponscripter": "NScripter",
}

#: 每引擎的文本清洗规则。字段都可以按实测继续加：
#:   name_prefix      —— 剥离开头的【人名】前缀
#:   collapse_doubling—— 折叠「每个字重复 2 次」的版本
#:   dedupe_window    —— 同一句多形态的去重窗口（秒）
#:   hook_hint        —— 面板里给用户的建议
ENGINE_PROFILES = {
    "TVP/KIRIKIRI": {
        "name_prefix": True, "collapse_doubling": True, "dedupe_window": 8.0,
        "hook_hint": "TVP/KIRIKIRI：优先用 GetTextExtentPoint32W:HQ8@0:gdi32.dll 这条钩子，"
                     "它通常能给出完整正文（实测 DRACU RIOT）。",
    },
    "WillPlus": {
        "name_prefix": True, "collapse_doubling": True, "dedupe_window": 8.0,
        "hook_hint": "WillPlus/AdvHD：Textractor 的 WillPlus 系钩子对不上这个引擎版本"
                     "（实测少女之剑：WillPlus 找不到函数、WillPlusW/A 找不到特征码、"
                     "WillPlus2 挂到了 Intel 显卡驱动的 DLL 上），只剩按字形抓的 GDI 钩子，"
                     "而字形有缓存 → 缺字严重。请改用 OCR 模式（面板 → 重新框选 OCR 区域）。",
    },
    "default": {
        "name_prefix": True, "collapse_doubling": True, "dedupe_window": 8.0,
        "hook_hint": "",
    },
}


def profile_for(engine: str) -> dict:
    return dict(ENGINE_PROFILES.get(engine) or ENGINE_PROFILES["default"])


def detect_engine(pid: int) -> str:
    """按进程加载的模块名猜引擎；读不到模块就返回 unknown（不影响功能）。"""
    for path in module_names(pid):
        low = path.lower()
        for name, keys in ENGINE_SIGNATURES:
            if any(key in low for key in keys):
                return name
    return "unknown"


def module_names(pid: int, limit: int = 0) -> list[str]:
    """该进程加载的模块全路径（识别引擎、排错都用它）；失败返回空表。"""
    pid = int(pid or 0)
    if not pid:
        return []
    out: list[str] = []
    try:
        import ctypes
        from ctypes import wintypes
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 必须声明参数类型：否则 HMODULE（指针）会被当作 64 位 int 传给 32 位形参，
        # 实测报「OverflowError: int too long to convert」→ 引擎恒为 unknown
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                                   wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel32.K32EnumProcessModules.restype = wintypes.BOOL
        psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                               ctypes.c_wchar_p, wintypes.DWORD]
        psapi.GetModuleFileNameExW.restype = wintypes.DWORD
        # 读模块名需要 VM_READ（只用 QUERY_LIMITED 会拿不到任何模块 → 引擎恒为 unknown）
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            return []
        try:
            needed = wintypes.DWORD()
            modules = (ctypes.c_void_p * 512)()
            if not kernel32.K32EnumProcessModules(handle, ctypes.byref(modules),
                                                  ctypes.sizeof(modules),
                                                  ctypes.byref(needed)):
                return []
            count = min(len(modules), max(0, needed.value // ctypes.sizeof(ctypes.c_void_p)))
            for index in range(count):
                buffer = ctypes.create_unicode_buffer(1024)
                if psapi.GetModuleFileNameExW(handle, modules[index], buffer, 1024):
                    out.append(buffer.value)
        finally:
            kernel32.CloseHandle(handle)
    except Exception as exc:
        config.log(f"module list failed: {exc}")
    return out[:limit] if limit else out


LINE_RE = re.compile(
    r"^\[([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):"
    r"([^\]]*):([^\]]*)\]\s?(.*)$")


def candidate_dirs() -> list[Path]:
    """常见安装位置：环境变量目录 + 各盘常见路径 + PATH。"""
    out: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        root = os.environ.get(env_name)
        if root:
            out += [Path(root) / "Textractor", Path(root) / "Textractor" / "x64",
                    Path(root) / "Downloads" / "Textractor", Path(root) / "Desktop" / "Textractor"]
    for drive in "CDEFGH":
        base = Path(f"{drive}:\\")
        try:
            if not base.exists():
                continue
        except OSError:
            continue
        out += [base / "Textractor", base / "Textractor" / "x64",
                base / "Tools" / "Textractor", base / "Tools" / "Textractor" / "x64",
                base / "Program Files" / "Textractor"]
    found = shutil.which("TextractorCLI") or shutil.which(CLI_NAME)
    if found:
        out.insert(0, Path(found))
    return out


def cli_builds(saved: str = "") -> list[dict]:
    """找到的所有 TextractorCLI 版本（x86 / x64 各算一个），带位数信息。

    Textractor 发布包里根目录是 x86 版，`x64\\` 是 64 位版；galgame 绝大多数是
    32 位，所以注入 32 位游戏必须用 x86 那份，选错会报「只能用 32 位」。
    """
    from . import locale as locale_mod

    seen: list[str] = []
    paths: list[Path] = []
    if saved:
        item = Path(saved)
        paths.append(item / CLI_NAME if item.is_dir() else item)
    for root in candidate_dirs():
        if root.suffix.lower() == ".exe":
            paths += [root]
            continue
        paths += [root / CLI_NAME, root / "x86" / CLI_NAME, root / "x64" / CLI_NAME,
                  root.parent / CLI_NAME]
    out: list[dict] = []
    for path in paths:
        try:
            if not path.is_file():
                continue
            key = str(path).lower()
            if key in seen:
                continue
            seen.append(key)
        except OSError:
            continue
        info = locale_mod.pe_bits(path)
        out.append({"path": str(path), "bits": int(info.get("bits") or 0),
                    "known": bool(info.get("ok"))})
    return out


def find_cli(saved: str = "", bits: int = 0) -> str:
    """按目标游戏位数挑一个 TextractorCLI.exe；找不到返回空串。"""
    builds = cli_builds(saved)
    if not builds:
        return ""
    if saved:
        exact = [b for b in builds if b["path"].lower() == str(saved).lower()]
        if exact:
            return exact[0]["path"]
    if bits:
        match = [b for b in builds if b["bits"] == bits]
        if match:
            return match[0]["path"]
    # 没有位数信息（或没有匹配版本）时优先 x86：galgame 大多数是 32 位
    prefer = [b for b in builds if b["bits"] == 32] or \
             [b for b in builds if "/x86/" in b["path"].replace("\\", "/").lower()] or builds
    return prefer[0]["path"]


def parse_hook_line(raw: str) -> dict | None:
    """解析 TextractorCLI 的一行，拿不到正文就返回 None。"""
    if not raw:
        return None
    match = LINE_RE.match(raw.rstrip("\r\n"))
    if not match:
        text = raw.strip()
        return {"text": text, "thread": "", "name": "", "code": ""} if text else None
    handle, pid, addr, ctx, ctx2, name, code, text = match.groups()
    text = text.strip()
    if not text:
        return None
    return {"text": text, "thread": f"{handle}:{pid}:{addr}:{ctx}:{ctx2}",
            "name": name, "code": code}


NAME_PREFIX_RE = re.compile(r"^(?:\u3010[^\u3011]{1,12}\u3011|\[[^\]]{1,12}\]|\uff3b[^\uff3d]{1,12}\uff3d)+")


def _kana_fold(ch: str) -> str:
    """片假名折成平假名：引擎逐字双写时常出现「ぺペ」这种混写配对。"""
    code = ord(ch)
    if 0x30A1 <= code <= 0x30F6:
        return chr(code - 0x60)
    return ch


def collapse_doubling(body: str) -> str:
    """每个字符恰好重复 2 次 → 压成 1 个。只用于「判断是不是同一句」，不动展示文本。"""
    out: list[str] = []
    i = 0
    while i < len(body):
        if i + 1 < len(body) and _kana_fold(body[i]) == _kana_fold(body[i + 1]):
            out.append(body[i])
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def normalize_for_dedupe(text: str) -> str:
    """去重用的归一化：折叠重复（含逐字双写）+ 去掉开头的【名字】+ 去掉标点空白。

    同一句台词常以三种形态先后到达：带名字前缀版、逐字重复版、干净版。
    归一化后它们是同一个串，只翻一次就够。
    """
    body = clean_hook_text(text)
    body = NAME_PREFIX_RE.sub("", body).strip()
    body = collapse_doubling(body)
    return re.sub(r"[\s\u300c\u300d\u300e\u300f\u3010\u3011\[\]\uff08\uff09()、。，,.!\uff01?\uff1f"
                  r"\u2026\u30fc\u301c~\u30fb:\uff1a;\uff1b-]", "", body)


RUN_RE = re.compile(r"(.)\1{2,}", re.DOTALL)


def collapse_runs(body: str) -> str:
    """把「同一个字连续重复 ≥3 次」压成 1 个（引擎逐字写缓冲时会这样）。

    只压 3 次以上：日文里的「！！」「……」这类两连是有意义的，不能动。
    """
    out = RUN_RE.sub(r"\1", body)
    tokens = out.split()
    if len(tokens) >= 2 and len(set(tokens)) == 1:
        out = tokens[0]                       # 「ABC ABC」这种整串重复
    return out


def collapse_repeats(text: str) -> str:
    """把「整行是同一段重复」还原成一段（Textractor 常见的重复句问题）。

    例：AAABBBCCC → ABC；【佑斗】【佑斗】【佑斗】 → 【佑斗】；
        おおおいいいいーー → おいー
    """
    body = (text or "").strip()
    n = len(body)
    if n >= 4:
        for period in range(1, n // 2 + 1):
            if n % period:
                continue
            block = body[:period]
            if block and block * (n // period) == body:
                return collapse_runs(block)
    return collapse_runs(body)


# --------------------------------------------------------------------------- #
# 写缓冲痕迹的还原
#
# 实测（DRACU RIOT / TVP-KIRIKIRI）：钩子拿到的是游戏「往同一个对话框缓冲区
# 反复写、每次重画都重写一遍」的过程，于是一行里会出现同一句台词的多个形态：
#     【佑斗】【佑斗】【佑斗】ABC AABBCC ABC
#     なななかかか…（逐字×3）  ・  …だだだ。。。今今にに至至るる…（×3 + ×2）
# 直接送去翻译就会把三段都翻一遍、或者翻出带重复的怪句子（用户反馈的
# 「三形态文本」）。下面这几个函数负责把「能证明是写缓冲痕迹」的部分还原成一句。
# --------------------------------------------------------------------------- #
def fold_char_runs(body: str, min_run: int = 3) -> str:
    """同一个字连续 ≥min_run 次 → 折成 1 个；标点/长音符等天然连写的字符不动。

    「なななかかか」→「なかなか」；「。。。」「！！」原样保留。
    """
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        j = i + 1
        while j < n and body[j] == ch:
            j += 1
        run = j - i
        if run >= min_run and ch not in KEEP_RUN_CHARS:
            out.append(ch)
        else:
            out.append(ch * run)
        i = j
    return "".join(out)


def _pair_run(body: str, start: int) -> int:
    """从 start 开始「成对相同」的对数（ぺペ 这种平/片假名混写也算一对）。"""
    pairs = 0
    i = start
    while i + 1 < len(body) and _kana_fold(body[i]) == _kana_fold(body[i + 1]):
        pairs += 1
        i += 2
    return pairs


def fold_doubling_spans(body: str, min_pairs: int = 3) -> str:
    """折叠「整段逐字双写」的片段，只折能证明的：连续 ≥min_pairs 对全部成对相同。

    「ここ」这类正常的叠字只有 1 对，永远不会被折；实测的引擎双写形态
    （「今今にに至至るる」「おははよようう」）动辄十几对，一定能被抓到。
    """
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        pairs = _pair_run(body, i)
        if pairs >= min_pairs:
            out.append("".join(body[i + 2 * k] for k in range(pairs)))
            i += 2 * pairs
            continue
        out.append(body[i])
        i += 1
    return "".join(out)


_PUNCT_EDGE = "。、，．,.！？!?…‥・「」『』（）()[]【】 \t\u3000"


def _skeleton(body: str) -> tuple[str, list[int], list[int]]:
    """骨架：去掉标点/引号/空白、连续相同字符合一，并记下每个骨架字符在原文里
    的起止位置（还原时把标点补回来）。"""
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, ch in enumerate(body):
        if ch in _PUNCT_EDGE or ch in "「」『』【】":
            continue
        if chars and chars[-1] == ch:
            ends[-1] = index
            continue
        chars.append(ch)
        starts.append(index)
        ends.append(index)
    return "".join(chars), starts, ends


def longest_repeat(body: str) -> str:
    """最长「至少出现两次」的子串（朴素后缀排序；台词行都很短，够用）。"""
    n = len(body)
    if n < 2:
        return ""
    order = sorted(range(n), key=lambda index: body[index:])
    best = ""
    for left, right in zip(order, order[1:]):
        if left > right:
            left, right = right, left
        size = 0
        while right + size < n and body[left + size] == body[right + size]:
            size += 1
        if size > len(best):
            best = body[left:left + size]
    return best


def _repeat_coverage(body: str, core: str) -> int:
    """整行里有多少字符属于「core 或它被截断的副本」。"""
    variants = [core]
    for cut in range(1, max(1, len(core) // 4) + 1):
        variants.append(core[:-cut])
    variants = [row for row in variants if len(row) >= 4]
    covered = 0
    index = 0
    n = len(body)
    while index < n:
        hit = 0
        for variant in variants:
            if body.startswith(variant, index):
                hit = len(variant)
                break
        if hit:
            covered += hit
        index += hit or 1
    return covered


def compare_key(text: str) -> str:
    """比较用骨架：去掉标点引号空白，并把连续相同字符压成一个。"""
    chars: list[str] = []
    for ch in text:
        if ch in _PUNCT_EDGE or ch in "「」『』【】":
            continue
        if chars and chars[-1] == ch:
            continue
        chars.append(ch)
    return "".join(chars)


def _similar(left: str, right: str, threshold: float = 0.6) -> bool:
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= threshold


def _collapse_quote_forms(body: str) -> str:
    """「形态1」「形态2」「形态3」——同一句被写多遍，各份之间是 」「。

    实测（DRACU RIOT）每一行都是这个结构：逐字×3 形态、×2 形态、干净形态，
    每份都被引号包住。只要判定这些份是同一句（骨架相似），就留最后一份
    ——写缓冲越写越准，最后一份就是干净的那句。
    """
    if "」「" not in body:
        return body
    parts = [part for part in body.split("」「") if part.strip()]
    if len(parts) < 2:
        return body
    folded = [collapse_repeats(fold_doubling_spans(fold_char_runs(part))) for part in parts]
    keys = [compare_key(part) for part in folded]
    last = keys[-1]
    if len(last) < 6:
        return body
    if not any(_similar(last, key) for key in keys[:-1]):
        return body
    out = folded[-1].strip()
    # 分隔符「」「」把最后一份的左引号留在了上一份的结尾，这里补/去多余括号，
    # 免得译文里带一个孤零零的 」
    while out and out[-1] in "」』" and out.count("「") < out.count("」"):
        out = out[:-1].rstrip()
    return out or body


def _collapse_by_coverage(body: str) -> str:
    """没有引号分隔时（例如「X。。X。X」「ABC AABBCC ABC」）按骨架重复判定。"""
    n = len(body)
    if n < 8 or n > 400:
        return body
    skeleton, starts, ends = _skeleton(body)
    total = len(skeleton)
    if total < 8:
        return body
    unit = longest_repeat(skeleton)
    if len(unit) < 4:
        return body
    chosen = ""
    best = (0, 0, 0)
    for size in range(4, len(unit) + 1):
        for candidate in (unit[:size], unit[-size:]):
            if len(candidate) < 4 or skeleton.count(candidate) < 2:
                continue
            covered = _repeat_coverage(skeleton, candidate)
            if covered < 0.85 * total:
                continue
            # 又长又铺得满的优先；打平时优先「落在行尾」的那份 —— 写缓冲最后写的
            # 才是当前这一句（跨份错位选出来的候选不会落在行尾）
            score = (covered * len(candidate), int(skeleton.endswith(candidate)),
                     len(candidate))
            if score > best:
                best, chosen = score, candidate
    if not chosen:
        return body
    last = skeleton.rfind(chosen)
    if last < 0:
        return body
    begin = starts[last]
    end = ends[last + len(chosen) - 1]
    # 只把左引号/左括号补回来；句号、逗号属于上一句，不能吞
    while begin > 0 and body[begin - 1] in "「『（([【":
        begin -= 1
    while end + 1 < n and body[end + 1] in _PUNCT_EDGE:      # 右引号/句读补回来
        end += 1
    return body[begin:end + 1].strip() or body


def collapse_duplicated_sentence(body: str) -> str:
    """同一句被写进同一行多遍（写缓冲的历史）时只留一份。

    实测原文（DRACU RIOT，一行三个形态）：
        【佑斗】×3「「「でででももも…？？？」」」「「ででもも…？？」」「でも…？」
    先按「」「」拆形态（最常见），拆不出来再按骨架重复覆盖率兜底。
    """
    collapsed = _collapse_quote_forms(body)
    if collapsed != body:
        return collapsed
    return _collapse_by_coverage(body)


def fold_written_repeats(text: str) -> str:
    """折叠全部写缓冲痕迹：逐字×N、成对双写、同句多份、整串重复。"""
    return collapse_repeats(collapse_duplicated_sentence(
        fold_doubling_spans(fold_char_runs(text))))


_CJK = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f"
_CJK_GAP_RE = re.compile(rf"(?<=[{_CJK}])[ \t\u3000]+(?=[{_CJK}])")


def tidy_ocr_text(text: str) -> str:
    """整理 OCR 结果：Windows OCR 会把日文按字切开（「出 会 っ て」），
    汉字/假名之间的空格要去掉，否则译文会被当成一堆孤立字。"""
    body = " ".join(str(text or "").split())
    return _CJK_GAP_RE.sub("", body)


_WRAP_CJK_RE = re.compile(rf"[{_CJK}\u3000-\u303f\uff01-\uff60]")


def join_wrapped(left: str, right: str) -> str:
    """把引擎折行后的续行接回一句：日文直接相连，西文之间补空格。"""
    if not left:
        return right
    if not right:
        return left
    if _WRAP_CJK_RE.match(left[-1]) or _WRAP_CJK_RE.match(right[0]):
        return left + right
    return f"{left} {right}"


def looks_like_speaker_name(text: str) -> bool:
    """像不像「说话人名字」那一行。

    不少引擎把名字单独发一条（实测悠刻のファムファタル 的 `アマリリス`）：很短、
    没有标点、也不是完整句子。这种行不该单独翻一句，应该并到下一句当【名字】。
    """
    body = (text or "").strip()
    if not body or len(body) > 12 or "\n" in body:
        return False
    if re.search(r"[。、，．！？!?…「」『』（）()\[\]]", body):
        return False
    return bool(re.search(rf"[{_CJK}]", body))


def split_name_prefix(body: str) -> tuple[str, str]:
    """拆开开头的【名字】前缀（可能重复写了多遍），返回 (名字, 正文)。"""
    match = NAME_PREFIX_RE.match(body)
    if not match:
        return "", body
    parts = re.findall(r"【[^】]{1,12}】|\[[^\]]{1,12}\]|［[^］]{1,12}］", match.group(0))
    names: list[str] = []
    for part in parts:
        # 引擎重画名字时会插空格（实测「【 佑斗 】」），统一压掉，译文才会干净
        clean = re.sub(r"\s+", "", part)
        if clean not in names:
            names.append(clean)
    return "".join(names), body[match.end():].lstrip()


def norm_name(text: str) -> str:
    """名字比较用：小写 + 去掉空白/下划线/点（「RIDDLE JOKER」==「RiddleJoker」）。"""
    return re.sub(r"[\s\-_.·]+", "", str(text or "").lower())


def clean_hook_text(text: str) -> str:
    """把写缓冲痕迹还原成一句台词；还原本就是重复噪声时返回空串。"""
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    name, rest = split_name_prefix(body)
    if not rest:
        return ""                     # 只有名字（引擎单独重画了一次名字）→ 不是台词
    rest = fold_written_repeats(rest).strip()
    if not rest:
        return ""
    return f"{name}{rest}" if name else rest


def residual_artifacts(text: str) -> list[str]:
    """仍然存在的重复痕迹（自检用：干净的台词应当返回空表）。"""
    body = str(text or "")
    found: list[str] = []
    for index in range(len(body) - 2):
        if body[index] == body[index + 1] == body[index + 2] \
                and body[index] not in KEEP_RUN_CHARS:
            found.append("run3")
            break
    index = 0
    while index < len(body) - 5:
        if _pair_run(body, index) >= 3:
            found.append("doubling")
            break
        index += 1
    if _collapse_by_coverage(body) != body:
        found.append("repeat")
    return found


GARBAGE_RE = re.compile(r"[\ue000-\uf8ff\ufffd\ufff0-\uffff\x00-\x08\x0b\x0c\x0e-\x1f]")
GOOD_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff01-\uff60a-zA-Z0-9\s，。、！？…—「」『』（）()：:；;・～~ー]")

#: 台词里可能出现的字符（日文/中文/拉丁/常见标点与全角符号）。除此之外的字符
#: （天城文、希伯来文、西里尔文…）基本都是「没转区/读错编码」的乱码。
EXPECTED_RE = re.compile(
    r"[\u0020-\u007e\u00a0-\u00ff\u2010-\u203b\u203c-\u206f\u2190-\u21ff"
    r"\u2460-\u24ff\u2500-\u257f\u25a0-\u25ff\u2600-\u27bf\u3000-\u303f"
    r"\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\ufe30-\ufe4f\uff01-\uff60\uff61-\uff9f\uffe0-\uffee]")

def looks_like_garbage(text: str) -> bool:
    """乱码判定：未转区（非日语代码页）时游戏会吐出假名+私用区/控制符混杂的串。"""
    body = (text or "").strip()
    if not body:
        return True
    if GARBAGE_RE.search(body):
        return True
    # 混进了意料之外的文字系统（实测白色相簿2 的乱码线程：
    # `इव孙ؔ䝬׋孙ؔ灐灒灟灹灱炄灰` —— 天城文/希伯来文混着汉字）
    others = sum(1 for ch in body if not EXPECTED_RE.match(ch))
    if others >= 2 and others / len(body) > 0.15:
        return True
    # 注意：这一条不能太激进。钩子是分片吐文本的，被截断的短句很容易凑不够
    # 有效字符比例，如果因此判成乱码，真文本所在线程会连着被误杀（反馈里的
    # 「真文本线程被丢弃，之后再也不翻译」就是这么来的）。
    if len(body) >= 6:
        good = len(GOOD_RE.findall(body))
        if good / len(body) < 0.5:
            return True
        if len(set(body)) <= 3:
            return True
    return False

KANA_RE = re.compile(r"[\u3040-\u30ff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def looks_like_dialogue(text: str) -> bool:
    """像不像游戏里的台词：有假名、有一定长度、不是纯符号/菜单。"""
    body = (text or "").strip()
    if len(body) < 4 or len(body) > 400:
        return False
    if looks_like_noise(body):
        return False
    kana = len(KANA_RE.findall(body))
    if kana >= 2 or (kana >= 1 and len(CJK_RE.findall(body)) >= 2):
        return True
    # 短台词（「あ…」「はい」这种只有一两个假名的）也算 —— 白色相簿2 里
    # 这类句子很多，不认的话真文本线程永远当不上领跑线程
    return kana >= 1 and bool(re.match(r"^[「『（(【]", body))


def looks_like_noise(text: str, max_chars: int = 1200) -> bool:
    """过滤纯数字/符号、过短、系统菜单这类不该翻的行。"""
    body = text.strip()
    if len(body) < 2 or len(body) > max_chars:
        return True
    if not re.search(r"[^\W\d_]", body, re.UNICODE):        # 全是数字/符号
        return True
    if any(word in body for word in NOISE_WORDS):
        return True
    if len(re.findall(r"\(&\w\)", body)) >= 2:
        return True                    # 「ファイル(&F)画面(&S)…」菜单栏
    # 视频/窗口/文件名之类（实测白色相簿2 的 `mv01`、`ActiveMovie Window`）：
    # 纯拉丁字母数字、没标点、又很短，不可能是日文台词
    if len(body) <= 24 and re.fullmatch(r"[A-Za-z0-9_.\- ]+", body):
        return True
    if looks_like_garbage(body):
        return True
    if len(set(body)) <= 2 and len(body) >= 6:              # 分割线之类
        return True
    return False


class VnTextEngine:
    """把钩子 / OCR 两种来源统一成一条文本流。"""

    def __init__(self, *, settings_getter, on_line, on_status=None, on_raw=None) -> None:
        self._get_settings = settings_getter
        self._on_line = on_line
        self._on_status = on_status
        self._on_raw = on_raw
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._procs: list[subprocess.Popen] = []
        self._targets: list[dict] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._game_id = ""
        self._pid = 0
        self._mode = ""                     # hook | ocr | ""
        self._cli = ""
        self._locked = ""
        self._seen: dict[str, dict] = {}
        self._last_line = ""
        self._last_norm = ""
        self._lines = 0
        self._error = ""
        # 默认框选：对话框常见位置（下三分之一），并避开底部的菜单按钮行
        self._region = {"x": 0.05, "y": 0.66, "w": 0.90, "h": 0.27}
        self._ocr_last = ""
        self._ocr_streak = 0
        self._lang = "ja-JP"
        self._interval = 0.9
        self._pending: dict[str, dict] = {}
        self._recent: list[tuple[str, float]] = []
        self._name_pending: dict | None = None
        self._merged = 0
        self._gated = 0
        self._engine = "unknown"
        self._profile: dict = {}
        self._leader = ""
        self._last_record: dict | None = None
        self._cli_bits = 0
        self._target_bits = 0

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        with self._lock:
            engine = self._mode
            active = self._active_key()
            threads = sorted(
                ({"key": key, "name": row["name"], "code": row["code"],
                  "count": row["count"], "dialogue": row.get("dialogue", 0),
                  "sample": row["sample"],
                  "active": key == active}
                 for key, row in self._seen.items()),
                key=lambda row: -row["count"])
            return {
                "ok": True,
                "running": bool(engine),
                "engine": engine,
                "game_id": self._game_id,
                "pid": self._pid,
                "cli": self._cli,
                "cli_bits": self._cli_bits,
                "target_bits": self._target_bits,
                "builds": cli_builds(str((self._get_settings() or {}).get("vntext_tractor_path") or "")),
                "locked": self._locked,
                "threads": threads[:12],
                "region": dict(self._region),
                "lang": self._lang,
                "lines": self._lines,
                "merged": self._merged,
                "gated": self._gated,
                "engine_name": self._engine,
                "hook_hint": (self._profile or {}).get("hook_hint") or "",
                "probe": {
                    "targets": [str(row.get("path") or "")[-40:] for row in (self._targets or [])][:3],
                    "threads": [f"{row['name']}:{row['count']}" for row in
                                sorted(self._seen.values(), key=lambda r: -r["count"])[:3]],
                },
                "error": self._error,
            }

    def _push_status(self) -> None:
        if not self._on_status:
            return
        try:
            self._on_status(self.status())
        except Exception as exc:
            config.log(f"vntext status callback failed: {exc}")

    def _active_kkey_placeholder(self) -> str:
        return ""

    def _active_by_score(self) -> str:
        if not self._seen:
            return ""
        return max(self._seen.items(),
                   key=lambda item: (item[1].get("dialogue", 0), item[1]["count"]))[0]

    def _active_key(self) -> str:
        if self._locked:
            return self._locked
        if self._leader and self._leader in self._seen:
            return self._leader
        return self._active_by_score()

    def _note_engine_hint(self, *parts: str) -> None:
        """从钩子输出里认出引擎（模块名认不出来时的兜底）。"""
        if self._engine not in ("", "unknown"):
            return
        hay = " ".join(str(part or "").lower() for part in parts)
        if not hay:
            return
        # `vnreng: INSERT Xxx` 是注入成功时的原文回显，最准：
        # 注意别只看到 "vnreng" 就当成 KiriKiri —— Leaf/Escu:de 也会打这一行
        insert = re.search(r"insert\s+([a-z0-9_+\-()]{2,24})", hay)
        # 没有 INSERT 时，`vnreng:WillPlusW: pattern not found` 这种也带引擎名
        if not insert:
            insert = re.search(r"vnreng:\s*([a-z0-9_+\-()]{2,24})", hay)
        if insert:
            token = insert.group(1).strip()
            for key, name in INSERT_ENGINE_NAMES.items():
                if token == key or token.startswith(key):
                    self._engine = name
                    self._profile = profile_for(name)
                    config.log(f"vntext engine from hook output: {name} (INSERT {token})")
                    self._push_status()
                    return
        for name, keys in HOOK_ENGINE_HINTS:
            if any(key in hay for key in keys):
                self._engine = name
                self._profile = profile_for(name)
                config.log(f"vntext engine from hook output: {name}")
                self._push_status()
                return

    # ------------------------------------------------------------------ #
    def start(self, game_id: str, pid: int, mode: str = "auto", exe: str = "") -> dict:
        self.stop()
        mode = mode if mode in ("hook", "ocr") else "auto"
        self._stop.clear()
        self._game_id = game_id
        self._pid = int(pid or 0)
        self._error = ""
        self._lines = 0
        self._last_line = ""
        self._last_norm = ""
        self._seen.clear()
        self._ocr_last = ""
        self._ocr_streak = 0
        self._merged = 0
        self._gated = 0

        settings = self._get_settings() or {}
        saved = str(settings.get("vntext_tractor_path") or "")
        # 有些引擎会把窗口标题/进程名塞进文本流（实测 AdvHD 的「剪贴板」线程
        # 一直回显 AdvHD_crack），这类只等于 exe 名的行直接丢掉
        self._noise_names: set[str] = set()
        for candidate in (exe, str(settings.get("_game_exe") or "")):
            if candidate:
                stem = Path(str(candidate))
                self._noise_names.add(norm_name(stem.name))
                self._noise_names.add(norm_name(stem.stem))
        try:
            from . import screencap as screencap_mod

            window = screencap_mod.main_window(self._pid)
            if window:
                title = screencap_mod.window_title(int(window.get("hwnd") or 0))
                if title:
                    self._noise_names.add(norm_name(title))
            # 视频/子窗口的标题也会被钩子当文本吐出来（`ActiveMovie Window`）
            for title in screencap_mod.window_titles(self._pid):
                self._noise_names.add(norm_name(title))
        except Exception as exc:
            config.log(f"vntext title probe failed: {exc}")
        self._noise_names.discard("")
        if exe:
            from . import locale as locale_mod

            self._target_bits = int(locale_mod.pe_bits(exe).get("bits") or 0)
        else:
            self._target_bits = 0
        self._cli = find_cli(saved, self._target_bits)
        if self._cli:
            from . import locale as locale_mod

            self._cli_bits = int(locale_mod.pe_bits(self._cli).get("bits") or 0)
        else:
            self._cli_bits = 0
        self._interval = max(0.3, float(settings.get("vntext_ocr_interval") or 0.9))

        self._pending.clear()
        self._leader = ""
        self._last_record = None
        self._name_pending = None
        threading.Thread(target=self._flush_loop, daemon=True,
                         name="aurora-vntext-flush").start()
        self._engine = detect_engine(self._pid)
        self._targets = self._collect_targets(self._pid, exe) if self._pid else []
        if self._engine in ("", "unknown"):
            # 候选进程（含子进程）的镜像路径里常直接带引擎 DLL 名
            haystack = " ".join(str(row.get("path") or "").lower() for row in self._targets)
            for name, keys in ENGINE_SIGNATURES:
                if any(key in haystack for key in keys):
                    self._engine = name
                    break
        self._profile = profile_for(self._engine)
        wanted_bits = {int(row.get("bits") or 0) for row in self._targets} - {0}
        started = False
        # 显式指定的 CLI 与「所有」候选进程位数都不符时才报错
        mismatch = (saved and self._cli_bits and wanted_bits
                    and self._cli_bits not in wanted_bits)
        if mismatch:
            self._error = "wrong-bitness"
        elif mode in ("auto", "hook") and self._cli and self._pid:
            started = self._start_hook()
            if not started and mode == "hook":
                self._error = "textractor-failed"
        if not started and mode in ("auto", "ocr"):
            started = self._start_ocr()
            if not started:
                from . import ocr as ocr_mod

                state = ocr_mod.status(self._lang)
                self._error = "no-window" if state["lang_ready"] else "no-language"
        if not started and not self._error:
            self._error = "no-textractor" if not self._cli else "hook-failed"
        elif started:
            self._error = ""
        self._push_status()
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        procs = list(self._procs) or ([self._proc] if self._proc else [])
        self._proc = None
        self._procs = []
        for proc in procs:
            try:
                if proc.stdin:
                    try:
                        proc.stdin.write(f"detach -P{self._pid}\n".encode("utf-16-le"))
                        proc.stdin.flush()
                    except Exception:
                        pass
                proc.terminate()
            except Exception as exc:
                config.log(f"textractor cli stop failed: {exc}")
        for thread in list(self._threads):
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.5)
        self._threads.clear()
        if self._mode:
            self._mode = ""
        return self.status()

    # ------------------------------------------------------------------ #
    def _collect_targets(self, pid: int, exe: str) -> list[dict]:
        """哪些进程可能在产出文本：主进程 + 它的子孙进程，各读一下 PE 位数。

        关键教训（实测反馈）：64 位游戏常由 32 位子进程渲染文本，文本线程的
        位数与游戏主 exe 不一致；只按主 exe 挑 CLI 就会挂错位数、读出乱码。
        """
        from . import locale as locale_mod, process as process_mod, proctree

        rows: list[dict] = []
        try:
            rows = proctree.snapshot()
        except Exception:
            rows = []
        candidates: list[tuple[int, str]] = []
        try:
            image = process_mod.process_image(pid)
            if image:
                candidates.append((int(pid), image))
        except Exception:
            pass
        if rows:
            try:
                for child in sorted(proctree.descendants(pid, rows) - {int(pid)}):
                    image = process_mod.process_image(child)
                    if image:
                        candidates.append((int(child), image))
            except Exception:
                pass
        out: list[dict] = []
        for child_pid, image in candidates[:6]:
            if os.path.normcase(image).startswith(os.path.normcase(os.environ.get("WINDIR", "C:\\Windows"))):
                continue                      # 系统进程不挂
            bits = int(locale_mod.pe_bits(image).get("bits") or 0)
            out.append({"pid": child_pid, "bits": bits, "path": image})
        if exe and not any(row["bits"] for row in out):
            bits = int(locale_mod.pe_bits(exe).get("bits") or 0)
            out.append({"pid": int(pid), "bits": bits, "path": str(exe)})
        return out

    def _start_hook(self) -> bool:
        targets = getattr(self, "_targets", None) or []
        groups: dict[int, list[int]] = {}
        for row in targets:
            groups.setdefault(int(row.get("bits") or 0), []).append(int(row["pid"]))
        if not groups:
            groups = {self._target_bits or 0: [self._pid]}
        started_any = False
        for bits, pids in groups.items():
            cli = self._cli if (not bits or not self._cli_bits
                                or bits == self._cli_bits) else find_cli(
                str((self._get_settings() or {}).get("vntext_tractor_path") or ""), bits)
            if not cli:
                continue
            if self._start_hook_one(cli, pids):
                started_any = True
        self._mode = "hook" if started_any else ""
        return started_any

    def _start_hook_one(self, cli: str, pids: list[int]) -> bool:
        self._cli = cli
        # 允许指向 .py / .cmd：自检里用假 CLI 模拟 TextractorCLI 的协议
        cmd = [cli]
        low = self._cli.lower()
        if low.endswith(".py"):
            cmd = [sys.executable, self._cli]
        elif low.endswith((".bat", ".cmd")):
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", self._cli]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW)
        except Exception as exc:
            config.log(f"textractor launch failed: {exc}")
            return False
        self._procs.append(proc)
        self._proc = proc
        self._mode = "hook"
        try:
            for target in pids:
                proc.stdin.write(f"attach -P{int(target)}\n".encode("utf-16-le"))
            proc.stdin.flush()
        except Exception as exc:
            config.log(f"textractor attach failed: {exc}")
            self._mode = ""
            return False
        thread = threading.Thread(target=self._hook_loop, args=(proc,), daemon=True,
                                  name="aurora-vntext-hook")
        self._threads.append(thread)
        thread.start()
        config.log(f"vntext hook attached pid={self._pid} cli={self._cli}")
        return True

    def _hook_loop(self, proc: subprocess.Popen) -> None:
        stream = proc.stdout
        if stream is None:
            return
        # 注意：不能用 stream.readline() —— UTF-16LE 的换行是 `0A 00`，
        # 二进制 readline 只吃掉 0x0A，会把后面的 0x00 留在缓冲里让后续每一行都错位。
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = stream.read1(4096)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while True:
                cut = buf.find(b"\n\x00")
                if cut < 0:
                    break
                raw = bytes(buf[:cut + 1])
                del buf[:cut + 2]
                text = raw.decode("utf-16-le", "ignore")
                parsed = parse_hook_line(text)
                if not parsed:
                    continue
                # 引擎把一句话折成多行发给 Textractor 时，CLI 会把整个文本原样打印，
                # 只有**第一行**带 `[handle:pid:addr:ctx:ctx2:名字:钩子码]` 头，后面
                # 几行是裸文本（实测 Escu:de 的悠刻のファムファタル：一句被折成 3 行）。
                # 以前这些续行会被当成「另一个匿名线程」的独立台词，于是一句话被拆成
                # 好几条依次翻译、悬浮窗逐条顶掉 —— 用户只来得及看到最后一行。
                if not parsed["thread"] and not parsed["name"] and self._last_record:
                    last = self._last_record
                    if time.time() - last["at"] <= 0.2 and not last["key"].startswith("0:0"):
                        merged = join_wrapped(last["text"], parsed["text"])
                        last["text"] = merged
                        last["at"] = time.time()
                        self._buffer_fragment(last["key"], merged, last["name"], last["code"])
                        continue
                self._note_engine_hint(parsed["text"], parsed["name"], parsed["code"])
                key = parsed["thread"] or parsed["name"] or "默认"
                self._last_record = {"key": key, "text": parsed["text"], "at": time.time(),
                                     "name": parsed["name"], "code": parsed["code"]}
                self._buffer_fragment(key, parsed["text"], parsed["name"], parsed["code"])
                continue
                with self._lock:
                    row = self._seen.setdefault(key, {"name": parsed["name"] or key,
                                                      "code": parsed["code"], "count": 0,
                                                      "sample": ""})
                    row["count"] += 1
                    if looks_like_dialogue(parsed["text"]):
                        row["dialogue"] = row.get("dialogue", 0) + 1
                    row["sample"] = parsed["text"][:60]
                    if parsed["code"]:
                        row["code"] = parsed["code"]
                    active = self._active_key()
                # 锁定支持前缀匹配：面板里抄了半截 key 也能锁定
                if self._locked and not (key == self._locked
                                         or key.startswith(self._locked)):
                    continue
                # 自动模式：只在「已经有一个明确在说台词的线程」时，才丢弃别的线程。
                # 之前按总行数判断，会被 Textractor 自己的状态行（例如「连接到 …」）
                # 抢先当上领跑者，把真正的台词线程整个丢掉——反馈里的「翻页不翻译」
                # 就是这个原因。
                if not self._locked and active and key != active:
                    leader_dialogue = self._seen.get(active, {}).get("dialogue", 0)
                    if leader_dialogue >= 3:
                        continue          # 已有明确的台词线程，其它线程一律不看
                self._emit(parsed["text"], "hook")
        if not self._stop.is_set():
            self._error = self._error or "hook-closed"
            self._push_status()

    # ------------------------------------------------------------------ #
    # 钩子文本是分片到达的：先按线程缓冲、合并成完整一句，静默 0.35s 再翻译。
    # 不这样做的话，截断的半句会被翻译错，还容易被误判成乱码。
    FRAGMENT_IDLE = 0.35

    def _buffer_fragment(self, key: str, text: str, name: str, code: str) -> None:
        now = time.time()
        with self._lock:
            row = self._seen.setdefault(key, {"name": name or key, "code": code,
                                              "count": 0, "sample": "", "dialogue": 0,
                                              "last_seen": now})
            row["last_seen"] = now
            if code:
                row["code"] = code
            pending = self._pending.get(key)
            if pending:
                old = pending["text"]
                if text.startswith(old) and len(text) > len(old):
                    pending["text"] = text      # 同一句被补全
                    pending["at"] = now
                    return
                if old.startswith(text):
                    pending["at"] = now         # 重复/回退，忽略
                    # 同一条短文本反复重发（说话人名字就是每翻一页重发一次）：
                    # 记一笔，识别「名字线程」时用得上 —— 两条名字行被 0.35 秒
                    # 缓冲合并成一条时，只靠 _register_line 计数是数不出来的
                    row["repeats"] = row.get("repeats", 0) + 1
                    return
                # 引擎可能把「缺字的前半段」先写出来、再补一份更完整的：
                # 只要一份基本包含另一份，就保留更长的那份，别当成新句子
                shorter, longer = (old, text) if len(old) <= len(text) else (text, old)
                if shorter and longer.find(shorter[:max(4, len(shorter) // 2)]) >= 0 \
                        and len(shorter) >= 0.6 * len(longer):
                    pending["text"] = longer
                    pending["at"] = now
                    row["repeats"] = row.get("repeats", 0) + 1
                    return
        if pending:
            self._flush_thread(key)             # 上一句先落地
        with self._lock:
            self._pending[key] = {"text": text, "at": time.time(), "code": code,
                                  "name": name}

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.12)
            now = time.time()
            # 攒着的「说话人名字」等不到下一句台词就自己发出去，别丢了
            with self._lock:
                pending_name = self._name_pending
                if pending_name and now - float(pending_name.get("at") or 0) > 3.0:
                    self._name_pending = None
                else:
                    pending_name = None
            if pending_name:
                self._emit(str(pending_name.get("text") or ""), "hook")
            with self._lock:
                keys = [k for k, row in self._pending.items()
                        if now - row["at"] >= self.FRAGMENT_IDLE]
            for key in keys:
                self._flush_thread(key)

    def _flush_thread(self, key: str) -> None:
        with self._lock:
            row = self._pending.pop(key, None)
        if not row:
            return
        text = " ".join(str(row["text"]).split())
        if not text:
            return
        if self._on_raw:
            try:
                self._on_raw({"text": text, "thread": key,
                              "name": str(row.get("name") or ""),
                              "code": str(row.get("code") or ""),
                              "at": time.time()})
            except Exception as exc:
                config.log(f"vntext raw callback failed: {exc}")
        self._register_line(key, text)

    def _register_line(self, key: str, text: str) -> None:
        """记账（台词计数/领跑线程）→ 线程门禁 → 去重 → 发射。

        顺序很关键（踩过坑）：**门禁要在去重登记之前**。之前先去重再门禁，
        被门禁丢掉的那一句已经写进「最近去重表」，真身线程随后送来的同一句
        会被当成重复吞掉 —— 整句就彻底没了（RIDDLE JOKER 两个同名钩子线程
        交替抢先时，表现为「一句有译文、一句根本没出现」）。
        """
        # 同一句台词常以多种形态、甚至跨线程先后到达（实测 DRACU RIOT 是
        # 【人名】前缀版 + 逐字双写版 + 干净版三份）。
        clean = clean_hook_text(text)
        norm = normalize_for_dedupe(text)
        config.log(f"vntext in [{key[:8]}] {text[:50]!r} -> {clean[:50]!r}")
        if not clean:
            return
        if norm_name(clean) in getattr(self, "_noise_names", ()):
            return
        # 菜单/系统行（セーブ・ロード・設定…）在这里就拦掉：
        # 它们既不该发射，更不能被下面的「说话人名字」逻辑当成名字，
        # 否则会把下一句台词污染成「【ロード】教室をあとにする。」而整句被丢掉
        max_chars = int((self._get_settings() or {}).get("vntext_max_chars") or 1200)
        if looks_like_noise(clean, max_chars):
            with self._lock:
                row = self._seen.setdefault(key, {"name": key, "code": "", "count": 0,
                                                  "sample": "", "dialogue": 0,
                                                  "last_seen": time.time()})
                row["count"] = row.get("count", 0) + 1
                row["last_seen"] = time.time()
            return
        with self._lock:
            row = self._seen.setdefault(key, {"name": key, "code": "", "count": 0,
                                              "sample": "", "dialogue": 0,
                                              "last_seen": time.time()})
            row["count"] += 1
            row["last_seen"] = time.time()
            if looks_like_speaker_name(clean):
                row["short"] = row.get("short", 0) + 1
            else:
                row["long"] = row.get("long", 0) + 1
            # 只出短名字、从不出长句的线程 = 「说话人名字」线程（实测 Escu:de）。
            # repeats 来自分片缓冲（同一条短文本反复重发），两条名字行被缓冲合并
            # 成一条时也能认出来
            name_like = row.get("short", 0) + row.get("repeats", 0)
            name_thread = name_like >= 2 and not row.get("long", 0)
            if looks_like_dialogue(clean):
                row["dialogue"] = row.get("dialogue", 0) + 1
            row["sample"] = clean[:60]
            leader = self._leader
            leader_seen = self._seen.get(leader, {}).get("last_seen", 0) if leader else 0
            if not leader or (leader != key and time.time() - leader_seen > 20):
                if row.get("dialogue", 0) >= 3:
                    self._leader = self._active_by_score()
            active = self._active_key()
            leader_dialogue = self._seen.get(active, {}).get("dialogue", 0)
        if name_thread:
            # 先攒着，等下一句台词拼成【名字】；超过 3 秒没有台词就当普通台词发出去
            self._name_pending = {"text": clean, "key": key, "at": time.time()}
            return
        if self._name_pending:
            with self._lock:
                pending, self._name_pending = self._name_pending, None
            if pending and pending["key"] != key and time.time() - pending["at"] <= 3.0:
                clean = f"【{pending['text']}】{clean}"
        if self._locked and not (key == self._locked or key.startswith(self._locked)):
            self._gated += 1
            return
        # 已经有明确在说台词的线程时，其它线程里**不像台词**的输出不看
        # （乱码/菜单动画多是它们产的）；像台词的照常走，交给下面的去重合并 ——
        # 两个同步在吐同一句的线程（RIDDLE JOKER）不该被整条丢掉
        if not self._locked and active and key != active and leader_dialogue >= 3 \
                and not looks_like_dialogue(clean):
            self._gated += 1
            config.log(f"vntext gated: {clean[:40]!r} ({key[:8]})")
            self._push_status()
            return
        window = max(20.0, float((self._profile or {}).get("dedupe_window") or 8.0))
        if len(norm) >= 6:
            now0 = time.time()
            with self._lock:
                self._recent = [(n, t) for n, t in self._recent if now0 - t <= window]
                for old, _t in self._recent:
                    same = (norm == old or norm in old or old in norm)
                    if not same and abs(len(norm) - len(old)) <= max(3, 0.25 * len(old)):
                        same = difflib.SequenceMatcher(None, norm, old).ratio() >= 0.9
                    if same:
                        self._merged += 1
                        config.log(f"vntext dup merged: {text[:40]!r}")
                        self._push_status()
                        return
                self._recent.append((norm, now0))
                del self._recent[:-8]
        self._emit(clean, "hook")

    # ------------------------------------------------------------------ #
    def _start_ocr(self) -> bool:
        from . import ocr

        if not ocr.available() or not ocr.has_language(self._lang):
            return False
        window = screencap.main_window(self._pid)
        if not window:
            return False
        self._mode = "ocr"
        # 把游戏窗口抬到最上面再开抓：被别的窗口盖住时 DWM 给的合成画面会缺图层
        # （实测 AdvHD 的对话框就是被盖住时抓不到的），抬起不抢焦点。
        try:
            from . import winapi

            winapi.raise_window(int(window.get("hwnd") or 0))
        except Exception:
            pass
        thread = threading.Thread(target=self._ocr_loop, args=(window,), daemon=True,
                                  name="aurora-vntext-ocr")
        self._threads.append(thread)
        thread.start()
        config.log(f"vntext ocr started pid={self._pid} region={self._region}")
        return True

    def _ocr_loop(self, window: dict) -> None:
        from . import ocr

        last_frame = b""
        while not self._stop.is_set():
            shot = screencap.capture(window, self._region)
            if shot.get("ok"):
                # 画面没变就别浪费一次 OCR：按固定步长抽样比较
                frame = shot["bgr"]
                step = max(3, len(frame) // 2048 // 3) * 3
                sample = frame[::step]
                if sample and sample == last_frame:
                    time.sleep(self._interval)
                    continue
                last_frame = sample
            if not shot.get("ok"):
                self._error = str(shot.get("error") or "capture-failed")
                self._push_status()
                time.sleep(1.5)
                continue
            result = ocr.recognize_bgr(shot["bgr"], shot["width"], shot["height"], self._lang)
            if not result.get("ok"):
                self._error = str(result.get("error") or "ocr-failed")
                self._push_status()
                time.sleep(1.5)
                continue
            self._error = ""
            text = tidy_ocr_text(result["text"])
            if text and text == self._ocr_last:
                self._ocr_streak += 1
            else:
                self._ocr_streak = 1
                self._ocr_last = text
            # 同一屏文字连续出现两次才认为画完了，避免半截台词
            if text and self._ocr_streak >= 2:
                max_chars = int((self._get_settings() or {}).get("vntext_max_chars") or 1200)
                if not looks_like_noise(text, max_chars):
                    # dedupe=True：同一屏文字只翻一次（OCR 每 0.9 秒抓一次，
                    # 不去重就会把同一句反复送给翻译）
                    self._emit(text, "ocr")
            time.sleep(self._interval)

    # ------------------------------------------------------------------ #
    def _emit(self, text: str, source: str, dedupe: bool = True) -> None:
        # 钩子文本先还原写缓冲痕迹；OCR 文本是识别结果，不折（折了反而会改动原文）
        body = clean_hook_text(text) if source == "hook" \
            else " ".join(collapse_repeats(str(text or "")).split())
        if not body:
            return
        max_chars = int((self._get_settings() or {}).get("vntext_max_chars") or 1200)
        if looks_like_noise(body, max_chars):
            return
        norm = normalize_for_dedupe(body)
        if dedupe and (body == self._last_line or (norm and norm == self._last_norm)):
            return
        if source == "ocr" and self._last_line and len(body) >= 8 \
                and len(self._last_line) >= 8 \
                and difflib.SequenceMatcher(None, body, self._last_line).ratio() >= 0.92:
            # OCR 每次识别的结果会有轻微抖动（多一个空格、掉一个标点），
            # 归一化去重抓不住，这里再挡一层
            return
        # 去重统一放在 _register_line 里做（那里能拿到线程 key，也能跨线程合并）；
        # 这里只保留「与上一句完全相同」的快速判断。
        self._last_line = body
        self._last_norm = norm
        self._lines += 1
        try:
            self._on_line({"text": body, "source": source, "game_id": self._game_id})
        except Exception as exc:
            config.log(f"vntext line callback failed: {exc}")
        self._push_status()

    # ------------------------------------------------------------------ #
    def lock_thread(self, key: str) -> dict:
        with self._lock:
            self._locked = str(key or "")
        self._push_status()
        return self.status()

    def send_hook(self, code: str) -> dict:
        code = str(code or "").strip()
        proc = self._proc
        if not code or proc is None or not proc.stdin:
            return {"ok": False, "error": "not-hook-mode"}
        try:
            proc.stdin.write(f"{code} -P{self._pid}\n".encode("utf-16-le"))
            proc.stdin.flush()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def set_region(self, region: dict) -> dict:
        with self._lock:
            self._region = {
                "x": max(0.0, min(1.0, float(region.get("x", 0)))),
                "y": max(0.0, min(1.0, float(region.get("y", 0)))),
                "w": max(0.02, min(1.0, float(region.get("w", 1)))),
                "h": max(0.02, min(1.0, float(region.get("h", 0.34)))),
            }
        self._push_status()
        return self.status()
