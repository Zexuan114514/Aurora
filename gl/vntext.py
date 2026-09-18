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
        "hook_hint": "WillPlus/AdvHD：Textractor 自带的 WillPlus 系钩子对不上这类 exe"
                     "（实测少女之剑：WillPlus 找不到函数、WillPlusW/A 找不到特征码、"
                     "WillPlus2 把地址算到 Intel 显卡驱动的 igc32.dll 上 → 乱码），只剩"
                     "按字形抓的 GDI 钩子，而字形有缓存 → 缺字。Aurora 会用**内存补全**"
                     "把缺字版配成完整台词（只读扫内存，不需要地址）；如果还想更稳，"
                     "可以在「翻译」面板里填一条专用钩子码 "
                     "`HQ-4@<模块内偏移>:<exe文件名>`（Q = UTF-16，S = 字节串，V = UTF-8）。"
                     "本机实测过的作品 Aurora 会自动带出这条码。",
    },
    "BGI/Ethornell": {
        "name_prefix": True, "collapse_doubling": True, "dedupe_window": 8.0,
        # 实测 秽翼のユースティア：BGI 钩子（hook 名就叫 BGI）给完整正文，
        # TextOutA/ExtTextOutW 这两条 GDI 钩子只给缺字版/乱码版，同一个进程里
        # 一起吐。留 0.6s 让两份都到齐，只翻完整那份。
        "variant_settle": 0.6,
        "hook_hint": "BGI/Ethornell：用 BGI 那条钩子（引擎自己的文本接口）就能拿到完整"
                     "正文；TextOutA/ExtTextOutW 是按字形抓的 GDI 钩子，会缺字，"
                     "自动模式已经把它的缺字版并掉了（实测 秽翼のユースティア）。",
    },
    "default": {
        "name_prefix": True, "collapse_doubling": True, "dedupe_window": 8.0,
        "hook_hint": "",
    },
}


def profile_for(engine: str) -> dict:
    return dict(ENGINE_PROFILES.get(engine) or ENGINE_PROFILES["default"])


#: WillPlus/AdvHD 系列的老问题：Textractor 自带的 WillPlus 钩子在这些游戏上会失配 ——
#: 实测 少女之剑与秘密的协奏曲：`vnreng:WillPlus: function call not found`、
#: WillPlusW/A 找不到特征码、WillPlus2 把地址算到了 Intel 显卡驱动 `igc32.dll` 上
#: （回显 `HQ-8*0@E8EB90:igc32.dll`，吐出来全是乱码），最后只剩按字形抓的
#: `GetGlyphOutlineW`，而引擎的字形有缓存 → 一行只抓到零星几个字。
#:
#: 实测出路（2026-09-19 在本机用 TextractorCLI 验证）：**用户钩子 + 直接给地址**。
#: Textractor 的 H-code 语法（读它的源码 `host/hookcode.cpp` 确认）是
#:     H<模式><data_offset>@<RVA>:<模块文件名>
#: 其中模式字母 `S`=字节串、`Q`=UTF-16 字符串、`V`=UTF-8 —— 少女之剑的文本是
#: UTF-16，所以必须用 `Q`（用 `S` 会把宽字符当单字节读成 `...0j0K0c0...`）。
#:
#: 下面每条记录都是我们自己在这台机器上实测出来的；exe 文件名 + 字节数 + CRC32
#: 三者同时匹配才启用，免得把某个版本的地址套到别的版本上。
WILLPLUS_AUTO_HOOKS = [
    {
        "name": "advhd_crack.exe",
        "size": 1992192,
        "crc32": 0x52EA5D63,
        "rva": 0xA22E,      # 图像基址 0x400000；这个 exe 没开 DYNAMICBASE，地址稳定
        "offset": -4,       # H-code 的 data_offset（Textractor 对负数会再按 ITH 减 4）
        "mode": "Q",        # Q = USING_STRING|USING_UNICODE（UTF-16）
        "game": "少女之剑与秘密的协奏曲",
        "note": "地址来自 LunaTranslator 日志的 `注入钩子: WillPlus3 0040A22E`；"
                "实测同一条地址在 Textractor 里用 `HQ-4@A22E:AdvHD_crack.exe` 就能"
                "吐完整正文（`１０年以上前の、初恋のことを。`），不再缺字。",
    },
]

#: H-code 的模式字母（来自 Textractor 源码 host/hookcode.cpp）：
#:   S = 字节串   Q = UTF-16 字符串   V = UTF-8
#:   A/B/W/H/M = 变体（大端 / 只读长度 / 十六进制转储等）
HOOK_CODE_MODES = ("S", "Q", "V", "A", "B", "W", "H", "M")


def file_fingerprint(path: str | Path) -> dict:
    """exe 的（文件名, 字节数, CRC32），用来对准「我们实测过的 hook 码」。"""
    import zlib

    try:
        data = Path(str(path)).read_bytes()
    except Exception:
        return {}
    return {"name": Path(str(path)).name.lower(), "size": len(data),
            "crc32": zlib.crc32(data) & 0xFFFFFFFF}


def match_willplus_hook(name: str, size: int, crc32: int) -> dict | None:
    """按指纹查我们自己的 WillPlus 实测记录；查不到返回 None。"""
    low = str(name or "").lower()
    try:
        size = int(size)
        crc32 = int(crc32)
    except Exception:
        return None
    for row in WILLPLUS_AUTO_HOOKS:
        if row["name"].lower() == low and int(row["size"]) == size \
                and int(row["crc32"]) == crc32:
            return dict(row)
    return None


def build_hook_code(row: dict, module: str = "") -> str:
    """按实测记录拼 H-code：`H<模式><data_offset>@<RVA>:<模块文件名>`。"""
    offset = int(row.get("offset") or 0)
    sign = "-" if offset < 0 else ""
    mode = str(row.get("mode") or "Q")[:1].upper() or "Q"
    return f"H{mode}{sign}{abs(offset):X}@{int(row['rva']):X}:{module}"


def willplus_hook_code(exe: str | Path) -> str:
    """这台机器上实测过的 WillPlus 专用 hook 码；没匹配到就返回空串。"""
    if not exe or os.environ.get("AURORA_DISABLE_AUTO_HOOK"):
        return ""
    fp = file_fingerprint(exe)
    if not fp:
        return ""
    row = match_willplus_hook(fp["name"], fp["size"], fp["crc32"])
    if not row:
        return ""
    return build_hook_code(row, Path(str(exe)).name)


def hook_code_matches(configured: str, actual: str) -> bool:
    """某条线程的钩子码是不是我们指定的那一条。

    Textractor 会把用户钩子码规范化后再回显（实测 `HV-4@A22E` 回显成
    `HS65001#-4@A22E`），所以退一步只比「地址 +（两边都有时的）模块」。
    """
    left = re.sub(r"\s+", "", str(configured or "")).lower()
    right = re.sub(r"\s+", "", str(actual or "")).lower()
    if not left or not right:
        return False
    if left == right:
        return True
    addr_left = re.search(r"@([0-9a-f]+)(?::([^:]+))?", left)
    addr_right = re.search(r"@([0-9a-f]+)(?::([^:]+))?", right)
    if not addr_left or not addr_right or addr_left.group(1) != addr_right.group(1):
        return False
    if addr_left.group(2) and addr_right.group(2) \
            and addr_left.group(2) != addr_right.group(2):
        return False
    return True


def looks_like_hook_code(text: str) -> bool:
    """看起来像不像 Textractor 的 H-code（界面上填错时早点拦下来）。

    形如 `H<模式><偏移>@<地址>[:<模块>]`：`HQ-4@A22E:AdvHD_crack.exe`。
    """
    body = re.sub(r"\s+", "", str(text or ""))
    if len(body) < 6 or body[:1].upper() != "H":
        return False
    if body[1:2].upper() not in HOOK_CODE_MODES:
        return False
    at = body.find("@", 2)
    if at < 0:
        return False
    tail = body[at + 1:]
    address, _, module = tail.partition(":")
    if not re.fullmatch(r"[0-9A-Fa-f]+", address or ""):
        return False
    return not tail.endswith(":")          # 有冒号就必须写模块名


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


#: `[handle:pid:addr:ctx:ctx2:名字:钩子码] 正文` —— 钩子码里**可能带冒号**（用户钩子
#: 形如 `HQ-4@A22E:AdvHD_crack.exe`），所以不能简单地按冒号切两段再各取一半：
#: 以前那条贪婪正则会把 `UserHook1:HQ-4@A22E:AdvHD_crack.exe` 切成
#: 名字=`UserHook1:HQ-4@A22E`、码=`AdvHD_crack.exe`（少了一段，认不出是我们的钩子）。
LINE_RE = re.compile(r"^\[([^\]]*)\]\s?(.*)$", re.DOTALL)


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
    head, text = match.groups()
    text = text.strip()
    if not text:
        return None
    # 头部按冒号切 6 刀：前 5 段是线程标识，第 6 段是钩子名，剩下的全算钩子码
    parts = head.split(":", 6)
    if len(parts) < 7:
        # 短行（例如 Textractor 自己的控制台行 `[0:0:FFFF...:控制台:HB0@0]` 是 7 段，
        # 而 `[默认]` 只有 1 段）：能凑出线程标识就凑，凑不出当纯文本
        thread = ":".join(parts[:5]) if len(parts) >= 5 else ""
        name = parts[5] if len(parts) > 5 else ""
        code = ""
    else:
        thread = ":".join(parts[:5])
        name = parts[5]
        code = parts[6]
    if not thread and not name:
        return {"text": text, "thread": "", "name": "", "code": ""}
    return {"text": text, "thread": thread, "name": name, "code": code}


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
    # 注意：长音符 `ー` 不算标点，"あー" 折成 "あ" 会让短句去重失效（实测 Siglus）
    return re.sub(r"[\s\u300c\u300d\u300e\u300f\u3010\u3011\[\]\uff08\uff09()、。，,.!\uff01?\uff1f"
                  r"\u2026\u301c~\u30fb:\uff1a;\uff1b-]", "", body)


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


_SENTENCE_END_RE = re.compile(r"[。．！？!?…」』]")


def fold_full_doubling(text: str) -> str:
    """整串都成对时才折一半（`女女子子`→`女子`）；`アマリリス` 这种正常叠音不动。"""
    body = str(text or "")
    if len(body) < 2 or len(body) % 2:
        return body
    if all(_kana_fold(body[i]) == _kana_fold(body[i + 1])
           for i in range(0, len(body), 2)):
        return body[::2]
    return body


def is_subsequence(short: str, long: str) -> bool:
    """short 的字符是否按顺序出现在 long 里（用来认「缺字变体」）。

    实测 Siglus 的 GDI 钩子会把同一句吐成只剩汉字的版本：`空雲落み` 之于
    `まるで、空から白い雲のかたまりが落ちてきたみたいに。`，正好是子序列。
    """
    if not short or not long or len(short) > len(long):
        return False
    it = iter(long)
    return all(ch in it for ch in short)


_CJK_ANY_RE = re.compile(rf"[{_CJK}]")

#: 按字形抓的 GDI 钩子（会漏字的那一类）
_GLYPH_HOOK_RE = re.compile(r"GetGlyphOutline|GetGlyphIndices|TextOut|ExtTextOut", re.I)


def _strip_ws(text: str) -> str:
    """判「缺字版」时把空白压掉：GDI 钩子吐出来的残片里常夹着空格
    （实测 WillPlus：真句 `姉さんは真面目を絵に…`，残片 `真面絵描 約束違真似`），
    带着空格去做子序列判断会直接失败、把残片当成新台词。"""
    return re.sub(r"\s+", "", str(text or ""))


def missing_chars_variant(short: str, long: str) -> bool:
    """`short` 是不是 `long` 的「缺字版」（同一句只画出来一部分）。

    实测 秽翼のユースティア（BGI/Ethornell）：同一个进程里 `TextOutA` 钩子按字形
    抓文本，字体里查不到的字就丢，吐出来的是 `視界黒塞`；引擎自带钩子随后吐出
    完整句 `視界を黒い何かが塞いだ。`。缺字版正好是完整版的**子序列**。
    """
    short = _strip_ws(short)
    long = _strip_ws(long)
    if len(short) < 3 or len(long) < 6:
        return False
    if len(short) > 0.8 * len(long):
        return False           # 只差一两个字：交给原来的相似度去重，别在这里动
    if not is_subsequence(short, long):
        return False
    # 整句正好是长句的开头（标点不算）→ 更像「短句被续写成下一句」
    # （`誰か。` → `誰か説明してほしい`），不是缺字版：缺字的版本是**中间**丢字，
    # 不会只剩开头那么多
    if normalize_for_dedupe(long).startswith(normalize_for_dedupe(short)):
        return False
    kept = len(_CJK_ANY_RE.findall(short))
    return kept >= max(3, int(0.6 * len(short)))


def looks_like_short_fragment(probe: str, pool) -> bool:
    """`probe` 是不是 pool 里某一句的残片（缺字/漏字的同一句）。

    两条历史规则（Siglus 实测）：
    ① 短、有汉字、没有句读，且是 pool 里某句的子序列（`群群飛飛`→`群飛`）；
    ② 比 pool 里最长的短 30% 以上，且每个字都能在 pool 里找到（变体有时是
       相邻两句拼起来的，例如 `遅２羽励寄添`）。
    """
    probe = _strip_ws(probe)
    texts = [_strip_ws(text) for text in (pool or [])]
    texts = [text for text in texts if text]
    if not texts or not (2 <= len(probe) <= 12) or _SENTENCE_END_RE.search(probe):
        return False
    if len(CJK_RE.findall(probe)) < max(2, len(probe) // 2):
        return False           # 只对「汉字为主」的残片动手，别误伤说话人名字
    if any(len(old) >= 4 and is_subsequence(probe, old) for old in texts):
        return True
    recent = texts[-4:]
    joined = "".join(recent)
    return len(probe) <= 0.7 * max(len(text) for text in recent) \
        and all(ch in joined for ch in probe)


#: 同一个进程里常常有两条钩子线程吐同一句台词的两份（完整版 + 缺字版）。
#: 先把候选行压住一小会，等这一批的两个版本都到齐再决定翻哪一份 —— 不这样做
#: 就会出现「同一句翻两遍、先翻缺字的再翻完整的」（实测 秽翼のユースティア）。
VARIANT_SETTLE = 0.55
#: 判「这两条是同一句的两个版本」时允许的最大时间差（秒）
VARIANT_WINDOW = 1.5


def _variant_pair(left: dict, right: dict) -> bool:
    """两条候选行是不是「同一句的两个版本」。

    要求：来自**不同线程**、时间挨着，且短的那条是长的那条的缺字版/残片。
    同一个线程的前后两句台词永远不算（由分片缓冲去处理）。
    """
    if not left or not right or left.get("key") == right.get("key"):
        return False
    try:
        gap = abs(float(left.get("at") or 0) - float(right.get("at") or 0))
    except Exception:
        return False
    if gap > VARIANT_WINDOW:
        return False
    short, long = (left, right) if len(left.get("probe") or "") <= len(right.get("probe") or "") \
        else (right, left)
    short_probe = str(short.get("probe") or "")
    long_probe = str(long.get("probe") or "")
    if not short_probe or not long_probe or len(short_probe) >= len(long_probe):
        return False
    if missing_chars_variant(short_probe, long_probe):
        return True
    return looks_like_short_fragment(short_probe, [long_probe])


def looks_like_system_spam(text: str, min_repeat: int = 4) -> bool:
    """系统字符串特征：同一个片段被下划线/空白重复很多遍。

    实测 SiglusEngine（SUMMER POCKETS REFLECTION BLUE）会疯狂重发场景名与资源表：
        `10_プロローグ072510_プロローグ072510_プロローグ0725…`（同一段重复 257 次）
    这类行没有句读、同一片段反复出现。必须拿**原始文本**判：清洗会把重复折掉，
    折完只剩 `10_プロローグ0725`，反而更像一句台词了。
    """
    body = str(text or "")
    if not body or _SENTENCE_END_RE.search(body):
        return False                     # 有句读 → 更像台词，放行
    if "__sys_" in body:
        return True
    tokens = [token for token in re.split(r"[_\s]+", body) if token]
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    if tokens and max(counts.values()) >= min_repeat:
        return True
    # 超长又没有句读 → 资源表；再退一步：某个片段在行里反复出现（`nonenonenone…`）
    if len(body) > 300:
        return True
    head = body[:800]
    repeat = longest_repeat(head)
    if len(repeat) >= 3 and len(repeat) * head.count(repeat) >= 0.5 * len(head):
        return True
    return False


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
    if "__sys_" in body:
        return True        # 引擎内部标记（实测 Siglus：__sys_scdata_init__ / __sys_bk_selline…）
    if re.match(r"^\d{1,3}_", body) and not _SENTENCE_END_RE.search(body):
        return True        # Siglus 场景名（10_プロローグ0725…），正常台词不会这么开头
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
        # 已过片段缓冲、还没定稿的候选行（等同一批里其它线程的「同句其它版本」到齐）
        self._staged: list[dict] = []
        self._settle = VARIANT_SETTLE
        self._recent: list[tuple[str, float]] = []
        self._recent_text: list[str] = []      # 最近几条「清洗后原文」（短句去重用）
        self._name_pending: dict | None = None
        self._merged = 0
        self._gated = 0
        self._completed = 0
        self._hook_code = ""
        self._hook_auto = ""
        #: CLI 打印「管道已连接」才算 attach 真的生效（专用钩子码要等这一步之后再发）
        self._pipe_seen = threading.Event()
        self._engine = "unknown"
        self._profile: dict = {}
        self._leader = ""
        self._last_record: dict | None = None
        self._cli_bits = 0
        self._target_bits = 0
        #: 用户钩子码（每游戏可填；也可由我们实测过的 WillPlus 记录自动带出）
        self._hook_code = ""
        self._hook_auto = ""

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
                "completed": self._completed,
                "engine_name": self._engine,
                "hook_code": self._hook_code,
                "hook_auto": self._hook_auto,
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
        # 优先「像正经句子」的线程（带句读/引号），其次才是台词计数与总行数 ——
        # 系统刷屏线程往往有大量含假名的资源名，光看行数会把它们排到前面
        # 最优先：用户/实测记录指定的专用钩子线程（WillPlus 的 `HQ-4@…`）
        return max(self._seen.items(),
                   key=lambda item: (item[1].get("preferred", False),
                                     item[1].get("prose", 0), item[1].get("dialogue", 0),
                                     item[1]["count"]))[0]

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
    def start(self, game_id: str, pid: int, mode: str = "auto", exe: str = "",
              hook_code: str = "") -> dict:
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
        self._hook_code = ""
        self._hook_auto = ""
        self._pipe_seen.clear()

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
        self._staged.clear()
        self._leader = ""
        self._last_record = None
        self._name_pending = None
        self._recent_text.clear()
        self._recent.clear()
        threading.Thread(target=self._flush_loop, daemon=True,
                         name="aurora-vntext-flush").start()
        self._engine = detect_engine(self._pid)
        self._targets = self._collect_targets(self._pid, exe) if self._pid else []
        # 用户钩子码：优先用这个游戏自己存的；没有就看是不是我们实测过的版本
        self._hook_auto = willplus_hook_code(exe)
        self._hook_code = str(hook_code or "").strip() or self._hook_auto
        if self._hook_code:
            config.log(f"vntext user hook code: {self._hook_code}"
                       f"{' (实测记录自动带出)' if not hook_code else ''}")
        if self._engine in ("", "unknown"):
            # 候选进程（含子进程）的镜像路径里常直接带引擎 DLL 名
            haystack = " ".join(str(row.get("path") or "").lower() for row in self._targets)
            for name, keys in ENGINE_SIGNATURES:
                if any(key in haystack for key in keys):
                    self._engine = name
                    break
        self._profile = profile_for(self._engine)
        # 引擎可以要求更长的「等同一个批次的另一个版本」时间（默认 0.55s）
        self._settle = max(0.0, float((self._profile or {}).get("variant_settle")
                                      or VARIANT_SETTLE))
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
        # 还在「等同一个批次的另一个版本」的候选行先定稿，别把最后一句吞掉
        try:
            self._resolve_staged(force=True)
        except Exception as exc:
            config.log(f"vntext staged flush on stop failed: {exc}")
        self._stop.set()
        try:
            from . import memmatch

            memmatch.reset(self._pid)
        except Exception:
            pass
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
        # 专用用户钩子（如 WillPlus 的 `HQ-4@A22E:AdvHD_crack.exe`）：Textractor 自带的
        # WillPlus 钩子在这类 exe 上会挂错模块，必须自己给地址。**要等 attach 生效再发** ——
        # 跟着 attach 同一批写进去会把 CLI 顶掉（实测：进程直接退出，一行文本都收不到）。
        if self._hook_code:
            sender = threading.Thread(target=self._send_hook_code_later,
                                      args=(proc, list(pids)), daemon=True,
                                      name="aurora-vntext-hookcode")
            self._threads.append(sender)
            sender.start()
        config.log(f"vntext hook attached pid={self._pid} cli={self._cli}")
        return True

    def _send_hook_code_later(self, proc: subprocess.Popen, pids: list[int]) -> None:
        """等 CLI 把 attach 处理完（打印「管道已连接」）再发专用钩子码。"""
        seen = self._pipe_seen.wait(timeout=6.0)
        if not seen and not self._stop.is_set():
            time.sleep(0.8)          # 老版本 CLI 不一定打这行，别死等
        if self._stop.is_set() or proc.poll() is not None:
            return
        code = self._hook_code
        if not code:
            return
        try:
            for target in pids:
                proc.stdin.write(f"{code} -P{int(target)}\n".encode("utf-16-le"))
            proc.stdin.flush()
            config.log(f"vntext user hook sent: {code}")
        except Exception as exc:
            config.log(f"vntext user hook send failed: {exc}")

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
                # attach 是否真的生效：CLI 会先打一行「管道已连接」（专用钩子码要等它）
                if "管道已连接" in parsed["text"] or "hijacking process" in parsed["text"]:
                    self._pipe_seen.set()
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
                # 专用用户钩子那条线程要优先当领跑线程（它的正文最完整）
                if self._hook_code and hook_code_matches(self._hook_code,
                                                         f"{name}:{code}"):
                    row["preferred"] = True
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
            # 分片缓冲清完后还要给「同一句的其它版本」留一点时间：这一步才真正发射
            self._resolve_staged()

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
        """清洗/噪声过滤 → 记账（台词计数/领跑线程）→ 压进候选池。

        候选池里的行要等 `_settle` 秒才定稿（见 `_resolve_staged`）：同一个引擎
        钩子常和 GDI 钩子一起吐同一句的两个版本（完整版 + 缺字版），必须等两份
        都到齐再决定翻哪一份 —— 否则同一句会被翻两遍，先翻错的再翻对的
        （实测 秽翼のユースティア）。
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
        # 系统刷屏（Siglus 的场景名/资源表）要拿**原始文本**判：
        # 清洗会把重复折掉、折完反而像一句正常台词
        known_spam = False
        with self._lock:
            known_spam = bool(self._seen.get(key, {}).get("spam"))
        system_spam = looks_like_system_spam(text)
        if known_spam or system_spam or looks_like_noise(text, 1200):
            with self._lock:
                row = self._seen.setdefault(key, {"name": key, "code": "", "count": 0,
                                                  "sample": "", "dialogue": 0,
                                                  "last_seen": time.time()})
                row["count"] = row.get("count", 0) + 1
                row["last_seen"] = time.time()
                if not known_spam:
                    if system_spam:
                        row["spam"] = True  # 反复重发的场景名/资源表：整个线程都没用
                    else:
                        # 普通噪声行（菜单词、分隔线、单字残片）只丢这一行。
                        # 以前这里直接整线程拉黑 —— 结果 TextOutA/GDI 钩子只是画出
                        # 一条 `─` 分隔线就被判成刷屏线程，后面真正的文本全被吞掉
                        # （实测 秽翼のユースティア：缺字版线程被误杀）。现在改成
                        # 「噪声攒够 3 条、又从来没吐过台词」才认定是系统线程。
                        row["noise"] = row.get("noise", 0) + 1
                        if row["noise"] >= 3 and not row.get("dialogue", 0):
                            row["spam"] = True
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
            if looks_like_dialogue(clean):
                row["dialogue"] = row.get("dialogue", 0) + 1
            if _SENTENCE_END_RE.search(clean):
                row["prose"] = row.get("prose", 0) + 1      # 带句读 = 更像正经台词
            row["sample"] = clean[:60]
            leader = self._leader
            leader_seen = self._seen.get(leader, {}).get("last_seen", 0) if leader else 0
            if not leader or (leader != key and time.time() - leader_seen > 20):
                if row.get("dialogue", 0) >= 3:
                    self._leader = self._active_by_score()
            else:
                # 领跑线程要跟着「最像正经台词」的线程走：Siglus 这类引擎会先冒出
                # 若干半截/缺字的线程，等真文本线程攒够句读就该换它当领跑
                best_key = self._active_by_score()
                if best_key and best_key != self._leader \
                        and self._seen.get(best_key, {}).get("prose", 0) \
                        > self._seen.get(self._leader, {}).get("prose", 0) + 1:
                    self._leader = best_key
            self._staged.append({"key": key, "clean": clean, "norm": norm,
                                 "probe": _strip_ws(collapse_doubling(clean)), "text": text,
                                 "at": time.time()})
            del self._staged[:-24]          # 保险：别让卡住的候选越堆越多
        return

    def _resolve_staged(self, force: bool = False) -> int:
        """把攒够时间的候选行定稿：同一句的多个版本只留最完整的那份。

        实测场景（秽翼のユースティア / BGI）：一次翻页里 GDI 钩子先吐缺字版
        `視界黒塞`，紧接着引擎钩子吐完整版 `視界を黒い何かが塞いだ。`。两条在
        同一个 0.35s 分片缓冲窗口里落地，所以这里把候选压住 `_settle` 秒，
        等两份都到齐 → 缺字版直接并掉，只翻完整版。

        另外还要防「差一点点就齐了」：如果某个候选已经等够时间、但池子里还有
        一条刚到的兄弟版本，就先不放它出去（`_variant_pair` 会认出来）。
        """
        now = time.time()
        with self._lock:
            staged = list(self._staged)
        if not staged:
            return 0
        ready: list[dict] = []
        young: list[dict] = []
        for cand in staged:
            if force or now - float(cand.get("at") or 0) >= self._settle:
                ready.append(cand)
            else:
                young.append(cand)
        emit_ready = [cand for cand in ready
                      if not any(_variant_pair(cand, other) for other in young)]
        if not emit_ready:
            return 0
        losers: set[int] = set()
        for index, cand in enumerate(emit_ready):
            for other in emit_ready[index + 1:]:
                if not _variant_pair(cand, other):
                    continue
                short = cand if len(cand["probe"]) <= len(other["probe"]) else other
                losers.add(id(short))
        with self._lock:
            self._staged = [cand for cand in self._staged if cand not in emit_ready]
        emitted = 0
        for cand in emit_ready:
            if id(cand) in losers:
                self._merged += 1
                config.log(f"vntext variant merged: {str(cand['clean'])[:30]!r}")
                continue
            self._promote(cand)
            emitted += 1
        if losers:
            self._push_status()
        return emitted

    def flush_staged(self) -> int:
        """立刻给所有候选行定稿（自检脚本用；运行时由 _flush_loop 按时定稿）。"""
        return self._resolve_staged(force=True)

    def _complete_from_memory(self, fragment: str) -> str:
        """把 GDI 钩子吐的缺字版补成完整台词（见 gl/memmatch.py）。"""
        try:
            from . import memmatch

            fixed = memmatch.complete(self._pid, fragment)
        except Exception as exc:
            config.log(f"memmatch failed: {exc}")
            return ""
        if fixed and fixed != fragment:
            self._completed += 1
            config.log(f"vntext memory completed: {fragment[:24]!r} -> {fixed[:40]!r}")
            self._push_status()
            return fixed
        return ""

    def _promote(self, cand: dict) -> None:
        """候选行定稿：缺字变体抑制 → 说话人名字合并 → 线程门禁 → 去重 → 发射。

        顺序很关键（踩过坑）：**门禁要在去重登记之前**。之前先去重再门禁，
        被门禁丢掉的那一句已经写进「最近去重表」，真身线程随后送来的同一句
        会被当成重复吞掉 —— 整句就彻底没了（RIDDLE JOKER 两个同名钩子线程
        交替抢先时，表现为「一句有译文、一句根本没出现」）。
        """
        key = str(cand.get("key") or "")
        clean = str(cand.get("clean") or "")
        norm = str(cand.get("norm") or "")
        text = str(cand.get("text") or "")
        probe = str(cand.get("probe") or "")
        # 只有按字形抓的 GDI 钩子会漏字（实测 WillPlus/AdvHD）：拿缺字版去**进程内存**
        # 里配出完整那句 —— 只读扫描，不需要引擎地址、不注入、也不会崩游戏
        with self._lock:
            hook_name = str((self._seen.get(key) or {}).get("name") or "")
        if self._pid and _GLYPH_HOOK_RE.search(hook_name):
            fixed = self._complete_from_memory(clean)
            if fixed:
                clean = fixed
                probe = _strip_ws(collapse_doubling(clean))
        # 缺字变体抑制（要放在「说话人名字」判定之前，否则 `越島` 这种残片会被
        # 当成名字挂到下一句上）：
        # ① 这句是刚发过那句的子序列（Siglus 的 GDI 钩子晚一步吐的汉字版）
        # ② 汉字 ≥2、没句读、比最近任一句都短，且每个字都能在最近几行里找到
        #   （变体有时是相邻两句拼起来的，例如 `遅２羽励寄添`）
        with self._lock:
            recent = list(self._recent_text)
        if looks_like_short_fragment(probe, recent):
            self._merged += 1
            config.log(f"vntext short fragment merged: {clean[:30]!r}")
            self._push_status()
            return
        with self._lock:
            row = self._seen.setdefault(key, {"name": key, "code": "", "count": 0,
                                              "sample": "", "dialogue": 0,
                                              "last_seen": time.time()})
            # 只出短名字、从不出长句的线程 = 「说话人名字」线程（实测 Escu:de）。
            # repeats 来自分片缓冲（同一条短文本反复重发），两条名字行被缓冲合并
            # 成一条时也能认出来
            name_like = row.get("short", 0) + row.get("repeats", 0)
            name_thread = name_like >= 2 and not row.get("long", 0)
            active = self._active_key()
            leader_dialogue = self._seen.get(active, {}).get("dialogue", 0)
            best_prose = max((info.get("prose", 0) for info in self._seen.values()),
                             default=0)
            best_dialogue = max((info.get("dialogue", 0) for info in self._seen.values()),
                                default=0)
        if name_thread:
            # 先攒着，等下一句台词拼成【名字】；超过 3 秒没有台词就当普通台词发出去
            # 名字本身也可能被引擎双写（实测 `女女子子`），压一下再用
            self._name_pending = {"text": fold_full_doubling(clean), "key": key,
                                  "at": time.time()}
            return
        if self._name_pending:
            with self._lock:
                pending, self._name_pending = self._name_pending, None
            if pending and pending["key"] != key and time.time() - pending["at"] <= 3.0:
                pending_text = str(pending.get("text") or "")
                # 「名字」其实是同一句的 GDI 缺字版时直接丢掉（实测 WillPlus：
                # GetGlyphOutlineW 线程吐 `家近離心倒`，真句是 `家が近所で、年が離れて…`，
                # 每个字都能在真句里按顺序找到）—— 否则会翻成「【家近離心倒】家が近所で…」
                if missing_chars_variant(pending_text, clean) \
                        or looks_like_short_fragment(pending_text, [clean]):
                    self._merged += 1
                    config.log(f"vntext name-like fragment dropped: {pending_text[:24]!r}")
                    self._push_status()
                elif not clean.startswith(pending_text):
                    # 这句话自己已经带了同一个名字（另一条线程的变体）就别再叠一层，
                    # 否则会出现「【羽依里】羽依里「あの」」
                    clean = f"【{pending_text}】{clean}"
        if self._locked and not (key == self._locked or key.startswith(self._locked)):
            self._gated += 1
            return
        # 一字不差的重复（短句归一化后可能只剩一两个字，下面的规则够不着）。
        # 放在名字合并之后，免得把「说话人名字重复出现」也算成重复丢掉
        if len(clean) >= 2:
            with self._lock:
                if clean in self._recent_text:
                    self._merged += 1
                    config.log(f"vntext same text merged: {clean[:30]!r}")
                    self._push_status()
                    return
                self._recent_text.append(clean)
                del self._recent_text[:-8]
        # （乱码/菜单动画多是它们产的）；像台词的照常走，交给下面的去重合并 ——
        # 两个同步在吐同一句的线程（RIDDLE JOKER）不该被整条丢掉
        # 领跑线程已经明显在说正经句子（带句读）时，其它线程只放行同样像正经句子的：
        # Siglus/WA2 这类引擎的 GDI 钩子会吐「缺字的同一句」（`海向てぶや`），
        # 它们没有句读，正好被挡在外面
        leader_prose = self._seen.get(active, {}).get("prose", 0)
        weak = not looks_like_dialogue(clean) \
            or (max(leader_prose, best_prose) >= 3 and not _SENTENCE_END_RE.search(clean))
        if not self._locked and active and key != active and weak \
                and max(leader_dialogue, best_dialogue) >= 2:
            self._gated += 1
            config.log(f"vntext gated: {clean[:40]!r} ({key[:8]})")
            self._push_status()
            return
        window = max(20.0, float((self._profile or {}).get("dedupe_window") or 8.0))
        if len(norm) >= 2:
            now0 = time.time()
            with self._lock:
                self._recent = [(n, t) for n, t in self._recent if now0 - t <= window]
                for old, _t in self._recent:
                    same = norm == old
                    if not same and len(norm) >= 6 and len(old) >= 6:
                        same = norm in old or old in norm
                    if not same and len(norm) >= 6 and len(old) >= 6 \
                            and abs(len(norm) - len(old)) <= max(3, 0.25 * len(old)):
                        same = difflib.SequenceMatcher(None, norm, old).ratio() >= 0.9
                    if not same:
                        # 名字前缀/后缀差异（Siglus 实测：`羽依里「あー……」` 与 `「あー……」`，
                        # 还有 GDI 钩子的半截句 `さしず…`）：多出来的那段当名字看 ——
                        # 2~12 个字、不带句读。这样「そう」→「そうか」不会误并
                        longer, shorter = (old, norm) if len(old) > len(norm) else (norm, old)
                        added = ""
                        if longer.endswith(shorter):
                            added = longer[:len(longer) - len(shorter)]
                        elif longer.startswith(shorter):
                            added = longer[len(shorter):]
                        # 只在「短句 + 名字/半截」这种形态上动手：短句限 2~4 字，
                        # 免得把相邻的两句（`こんにちは` → `こんにちは、元気？`）错并
                        # 另外要求短句别太短：`誰か。` 之于 `誰か説明してほしい──`
                        # 这种「短句整句被长句包住」是真台词，不能当名字前缀并掉
                        if 2 <= len(shorter) <= 4 and added and 2 <= len(added) <= 12 \
                                and len(shorter) >= 0.35 * len(longer) \
                                and not _SENTENCE_END_RE.search(added) \
                                and re.search(rf"[{_CJK}]", added):
                            same = True
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

    def set_hook_code(self, code: str) -> dict:
        """改「专用用户钩子码」：记住它（用于优先选线程）并立刻发给正在跑的 CLI。"""
        code = " ".join(str(code or "").split())
        with self._lock:
            self._hook_code = code
        if not code:
            return {"ok": True, "hook_code": ""}
        result = self.send_hook(code)
        result["hook_code"] = code
        self._push_status()
        return result

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
