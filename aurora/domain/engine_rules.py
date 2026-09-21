"""引擎规格与 H-code（纯数据 + 纯函数）：引擎清洗档位、实测指纹表、钩子码拼装与解析。

文件 IO（读 exe 算 CRC32、探测 CLI）留在 `gl/vntext.py`；这里只负责判定与拼装。
"""
from __future__ import annotations

import re



#: 引擎识别特征（按进程加载的模块名判断；这些都是我们自己观察到的模块名，
#: 不复制 Textractor / LunaHook 的引擎表或钩子码数据）
ENGINE_SIGNATURES = (
    ("TVP/KIRIKIRI", ("tvp(kirikiri)", "kirikiri", "krkr", "tvp_", "krkrz")),
    ("WillPlus", ("willplus", "advhd", "will_", "wpm")),
    ("BGI/Ethornell", ("bgi", "ethornell", "buriko")),
    # Artemis/Emote（あざらしそふと 等）：引擎运行时是 emotedriver.dll（自己用
    # D3D11 画字、不碰 GDI），另有 iarsys64.dll 辅助 —— 实测 アマカノ３
    ("Artemis/Emote", ("emotedriver", "iarsys", "artemis")),
    ("Siglus", ("siglus", "ave;new")),
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
    ("Artemis/Emote", ("artemis",)),
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
    "siglus": "Siglus", "siglusengine": "Siglus", "artemis": "Artemis/Emote",
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
    "Artemis/Emote": {
        "name_prefix": True, "collapse_doubling": True, "dedupe_window": 8.0,
        "hook_hint": "Artemis/Emote：引擎自己用 D3D11 画字（emotedriver.dll 只导入"
                     "KERNEL32 + D3DCOMPILER_47），GDI 文本钩子全空；Textractor 也没有"
                     "这个引擎的专用钩子。点「找不到文本？开始侦测」让 Aurora 自己找："
                     "它会按绘制函数特征码定位候选、逐个试寄存器偏移，实测 アマカノ３ 十秒内"
                     "就能拿到 HS65001#-6C@1B1F70:Amakano3.exe；本机实测过的作品还会自动"
                     "带出这条码。临时也可以用 OCR 模式。",
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
        "date": "2026-09-19",
        "sample": "１０年以上前の、初恋のことを。",
        "note": "地址来自 LunaTranslator 日志的 `注入钩子: WillPlus3 0040A22E`；"
                "实测同一条地址在 Textractor 里用 `HQ-4@A22E:AdvHD_crack.exe` 就能"
                "吐完整正文（`１０年以上前の、初恋のことを。`），不再缺字。",
    },
    {
        # Artemis / Emote（アマカノ３ = 甜蜜女友 3）：引擎自己用 D3D11 画字，
        # GDI 钩子全空。用户用 MisakaHookFinder（内嵌 Textractor 的「文本搜索」：
        # 先在内存里找到变化的文本，再找出读它的代码）搜到的特殊码实测可用：
        #     HS65001#-6C@1401B1F70   （基址 0x140000000 → RVA 0x1B1F70）
        # 这里按「模块 + RVA」的形式存，换一次加载地址也不会失效。
        "name": "amakano3.exe",
        "size": 5170176,
        "crc32": 0xA1FF529B,
        "rva": 0x1B1F70,
        "offset": -0x6C,
        "mode": "S",        # S = 字节串（这份文本是 UTF-8，见下面的 codepage）
        "codepage": 65001,  # HS65001#… = UTF-8
        "game": "アマカノ３（甜蜜女友 3）",
        "date": "2026-09-19",
        "sample": "明らかに、詩夢の顔が青い。",
        "note": "地址来自 MisakaHookFinder 搜出的 `HS65001#-6C@1401B1F70`；"
                "实测能完整提取对话（`明らかに、詩夢の顔が青い。`）。",
    },
]



#: H-code 的模式字母（来自 Textractor 源码 host/hookcode.cpp）：
#:   S = 字节串   Q = UTF-16 字符串   V = UTF-8
#:   A/B/W/H/M = 变体（大端 / 只读长度 / 十六进制转储等）
HOOK_CODE_MODES = ("S", "Q", "V", "A", "B", "W", "H", "M")


def match_willplus_hook(name: str, size: int, crc32: int,
                        rules: list[dict] | None = None) -> dict | None:
    """按指纹查我们自己的 WillPlus 实测记录；查不到返回 None。

    `rules` 由调用方给（P6 起是规则包加载出来的行）；不传时用内置常量，
    这样 domain 依旧是纯计算、不碰文件。
    """
    low = str(name or "").lower()
    try:
        size = int(size)
        crc32 = int(crc32)
    except Exception:
        return None
    for row in (rules if rules is not None else WILLPLUS_AUTO_HOOKS):
        if row["name"].lower() == low and int(row["size"]) == size \
                and int(row["crc32"]) == crc32:
            return dict(row)
    return None


def build_hook_code(row: dict, module: str = "") -> str:
    """按实测记录拼 H-code：`H<模式>[<编码>#]<data_offset>@<RVA>:<模块文件名>`。"""
    offset = int(row.get("offset") or 0)
    sign = "-" if offset < 0 else ""
    mode = str(row.get("mode") or "Q")[:1].upper() or "Q"
    codepage = row.get("codepage")
    page = f"{int(codepage)}#" if codepage else ""
    return f"H{mode}{page}{sign}{abs(offset):X}@{int(row['rva']):X}:{module}"


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


#: `[handle:pid:addr:ctx:ctx2:名字:钩子码] 正文` —— 钩子码里**可能带冒号**（用户钩子
#: 形如 `HQ-4@A22E:AdvHD_crack.exe`），所以不能简单地按冒号切两段再各取一半：
#: 以前那条贪婪正则会把 `UserHook1:HQ-4@A22E:AdvHD_crack.exe` 切成
#: 名字=`UserHook1:HQ-4@A22E`、码=`AdvHD_crack.exe`（少了一段，认不出是我们的钩子）。
LINE_RE = re.compile(r"^\[([^\]]*)\]\s?(.*)$", re.DOTALL)


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
