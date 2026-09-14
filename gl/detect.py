"""从可执行文件路径推断游戏名，并对候选结果打分。"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

# 常见的“非游戏名”目录，遇到时继续向上寻找
GENERIC_DIRS = {
    "bin", "binaries", "binary", "win64", "win32", "win", "x64", "x86", "x86_64",
    "game", "games", "app", "apps", "build", "builds", "dist", "release", "releases",
    "retail", "debug", "content", "data", "system", "engine", "source", "src",
    "client", "server", "core", "main", "start", "run", "launcher", "launch",
    "steamapps", "common", "no-dvd", "crack", "cracked", "crackfix", "codex",
    "goldberg", "fitgirl", "plaza", "skidrow", "empress", "elamigos", "rune",
    "prophet", "darksiders", "tenoke", "razor1911", "reloaded", "gog", "epic",
    "program files", "program files (x86)", "unreal engine", "unity", "resources",
    "assets", "packages", "windows", "win64-shipping", "shipping", "final",
}

# 名字里出现但不影响匹配的噪音词（仅降低权重，不直接删除）
NOISE = {
    "the", "a", "an", "of", "and", "for", "to", "in", "on", "at", "with",
    "game", "games", "exe", "app", "application", "client", "launcher", "launch",
    "win", "win64", "win32", "x64", "x86", "shipping", "final", "release", "retail",
    "setup", "install", "installer", "v", "ver", "version", "demo", "beta", "alpha",
    "crack", "cracked", "repack", "rip", "no", "dvd", "steam", "gog", "epic",
    "fitgirl", "codex", "plaza", "skidrow", "empress", "goldberg", "tenoke",
    "rune", "reloaded", "elamigos", "edition", "remaster", "remastered",
}

_EXT_NOISE = re.compile(
    r"(?:[_\-. ](?:win64|win32|x64|x86|shipping|final|release|retail|"
    r"launcher|setup|installer|demo|beta|alpha|v\d+(?:[._]\d+)*|"
    r"\d+[._]\d+(?:[._]\d+)*))+$",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"[\(\[\{（【][^\)\]\}）】]*[\)\]\}）】]")
#: 归一化时保留：英数字 + 日文假名（平假名/片假名）+ 汉字（含扩展区与兼容区）
_KEEP = "0-9a-zA-Z\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f"
_SEP = re.compile(f"[^{_KEEP}]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_TRAIL_YEAR = re.compile(r"(?:[\s_\-.]+(?:19|20)\d{2})$")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def _clean_name(raw: str) -> str:
    """去掉扩展名噪音、括号内容、版本号等。"""
    text = (raw or "").strip()
    text = _BRACKETS.sub(" ", text)
    text = _EXT_NOISE.sub("", text)
    text = _TRAIL_YEAR.sub("", text)
    text = text.replace("_", " ").strip(" -_.")
    # camelCase / PascalCase 拆分，便于与商店名比对
    text = _CAMEL.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def norm(text: str) -> str:
    """归一化：仅保留字母数字与汉字，全部小写。"""
    return _SEP.sub("", (text or "").lower())


def tokens(text: str) -> set[str]:
    parts = _SEP.split((text or "").lower())
    out = set()
    for part in parts:
        if not part or len(part) < 2:
            continue
        if part in NOISE:
            continue
        out.add(part)
    return out


def _is_meaningful(value: str) -> bool:
    """看起来像正式游戏名（而不是 b1 / x64 / 1234 这类代号）。"""
    key = norm(value)
    if len(key) < 4:
        return False
    if key in GENERIC_DIRS:
        return False
    if re.fullmatch(r"[\d._-]+", key):
        return False
    return True


def describe_path(exe: Path) -> dict:
    """分析可执行文件路径，返回候选查询名（按可信度排序）及路径上下文。

    优先级：steamapps/common/<游戏名> > 有意义的 exe 名 > 上层目录名 > 短代号 exe 名
    """
    exe = Path(exe)
    stem = exe.stem
    parent = exe.parent

    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()

    def push(priority: int, value: str) -> None:
        cleaned = _clean_name(value)
        key = norm(cleaned)
        if not key or len(key) < 2:
            return
        if key in seen:
            # 同一个名字的两种写法：优先保留带空格/大写的展示形式
            for index, (pri, existing) in enumerate(ranked):
                if norm(existing) == key and " " not in existing and " " in cleaned:
                    ranked[index] = (pri, cleaned)
                    break
            return
        seen.add(key)
        ranked.append((priority, cleaned))

    # 1) Steam 布局：.../steamapps/common/<游戏名>/...
    parts = list(exe.parts)
    lower_parts = [p.lower() for p in parts]
    if "common" in lower_parts:
        idx = len(lower_parts) - 1 - lower_parts[::-1].index("common")
        if idx + 1 < len(parts) - 1:
            push(0, parts[idx + 1])

    # 2) exe 文件名（短代号 / 通用名降权）
    cleaned_stem = _clean_name(stem)
    push(1 if _is_meaningful(cleaned_stem) else 8, cleaned_stem)

    # 3) 向上逐级寻找目录名
    current = parent
    for depth in range(4):
        if current is None or current == current.parent:
            break
        name = current.name
        if name:
            cleaned = _clean_name(name)
            if cleaned.lower() in GENERIC_DIRS or re.fullmatch(r"[\d._-]+", cleaned):
                pass
            elif _is_meaningful(cleaned):
                push(2 + depth, name)
            else:
                push(9 + depth, name)
        current = current.parent

    ranked.sort(key=lambda item: item[0])
    candidates = [value for _, value in ranked]

    queries: list[str] = []
    strong_queries: list[str] = []
    for value in candidates:
        is_strong = _is_meaningful(value)
        for variant in _variants(value):
            if variant not in queries:
                queries.append(variant)
                if is_strong:
                    strong_queries.append(variant)

    return {
        "exe_stem": stem,
        "exe_name": exe.name,
        "dir_name": parent.name,
        "candidates": candidates,
        "queries": queries[:8],
        "strong_queries": strong_queries[:4],
    }


def _variants(value: str) -> list[str]:
    out = [value]
    compact = re.sub(r"\s+", " ", value).strip()
    if compact != value:
        out.append(compact)
    # 去掉结尾的罗马数字 / 序号
    stripped = re.sub(r"\s+(?:i{1,3}|iv|v|vi{1,3}|ix|xi{1,3})\s*$", "", value, flags=re.I)
    if stripped and stripped != value and len(norm(stripped)) >= 3:
        out.append(stripped.strip())
    if not has_cjk(value):
        joined = norm(value)
        if joined and joined != norm(compact):
            out.append(joined)
    return [v for v in out if v and len(norm(v)) >= 2]


def similarity(query: str, name: str) -> float:
    """0~1 的相似度分数，偏向“完全一致 / 前缀一致”。"""
    nq, nn = norm(query), norm(name)
    if not nq or not nn:
        return 0.0
    if nq == nn:
        return 1.0

    ratio = difflib.SequenceMatcher(None, nq, nn).ratio()
    short, long_ = (nq, nn) if len(nq) <= len(nn) else (nn, nq)
    penalty = (len(short) / len(long_)) ** 0.5

    if nq in nn:
        ratio = max(ratio, (0.82 + 0.16 * (len(nq) / len(nn))) * penalty)
    elif nn in nq:
        ratio = max(ratio, (0.72 + 0.16 * (len(nn) / len(nq))) * penalty)

    tq, tn = tokens(query), tokens(name)
    if tq and tn:
        inter = len(tq & tn)
        union = len(tq | tn)
        if inter:
            ratio = max(ratio, 0.5 + 0.45 * (inter / union))

    return round(min(ratio, 1.0), 4)


def score_candidate(queries: list[str], name: str, kind: str = "app") -> float:
    """对商店搜索结果打分：取所有查询变体中的最高分。"""
    best = 0.0
    for q in queries:
        best = max(best, similarity(q, name))
    if kind != "app":
        best *= 0.5
    return round(best, 4)
