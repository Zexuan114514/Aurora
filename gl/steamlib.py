"""扫描本机 Steam 游戏库，给出可以直接导入的游戏列表。

数据来源是 Steam 自己的清单文件（`appmanifest_*.acf`），里面的 appid 与商店名
是权威值 —— 用它导入既不用猜名字，也能直接按 appid 拿到准确的中文简介。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

#: 明显不是游戏本体的可执行文件
SKIP_EXES = {
    "unins000.exe", "unins001.exe", "unins002.exe", "dxsetup.exe", "setup.exe",
    "install.exe", "installer.exe", "vcredist_x64.exe", "vcredist_x86.exe",
    "unitycrashhandler32.exe", "unitycrashhandler64.exe", "crashreportclient.exe",
    "ue4prereqsetup_x64.exe", "ue4prereqsetup.exe", "python.exe", "steam.exe",
    "steamwebhelper.exe", "steamservice.exe",
}

#: 不要往里翻的目录
SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows", "appdata",
    "program files", "program files (x86)", "programdata", "node_modules",
    ".git", ".svn", "__pycache__", "redist", "_commonredist", "commonredist",
    "directx", "vcredist", "dotnet", "support", "docs", "documentation",
    "steamworks", "tools", "content", "engine", "extras", "thirdparty",
}

MAX_DEPTH = 2

_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')
_APPID_RE = re.compile(r'"appid"\s+"(\d+)"')
_NAME_RE = re.compile(r'"name"\s+"([^"]*)"')
_INSTALLDIR_RE = re.compile(r'"installdir"\s+"([^"]*)"')


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+", "", (text or "").lower())


def steam_root() -> Path | None:
    """Steam 安装目录（注册表优先，其次常见路径）。"""
    candidates: list[Path] = []
    try:
        import winreg

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    value = str(winreg.QueryValueEx(handle, "SteamPath")[0])
                if value:
                    candidates.append(Path(value))
            except OSError:
                continue
    except Exception:
        pass

    for drive in "CDEFGH":
        candidates.append(Path(f"{drive}:\\Steam"))
        candidates.append(Path(f"{drive}:\\Program Files (x86)\\Steam"))
        candidates.append(Path(f"{drive}:\\Program Files\\Steam"))

    for path in candidates:
        try:
            if (path / "steamapps").is_dir():
                return path
        except OSError:
            continue
    return None


def library_paths(root: Path) -> list[Path]:
    """所有库目录（含 libraryfolders.vdf 里登记的外部库）。"""
    out: list[Path] = []

    def push(path: Path) -> None:
        try:
            resolved = Path(os.path.normpath(str(path)))
        except Exception:
            return
        if resolved not in out and (resolved / "steamapps").is_dir():
            out.append(resolved)

    push(root)
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in _PATH_RE.findall(text):
        push(Path(raw.replace("\\\\", "\\")))
    return out


def _manifests(library: Path) -> list[dict]:
    """读某个库里所有 appmanifest，返回 [{appid, name, installdir, dir}]。"""
    rows: list[dict] = []
    steamapps = library / "steamapps"
    for acf in sorted(steamapps.glob("appmanifest_*.acf")):
        try:
            text = acf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        appid = _APPID_RE.search(text)
        name = _NAME_RE.search(text)
        installdir = _INSTALLDIR_RE.search(text)
        if not (appid and installdir):
            continue
        folder = steamapps / "common" / installdir.group(1)
        rows.append({
            "appid": int(appid.group(1)),
            "name": (name.group(1).strip() if name else installdir.group(1)),
            "installdir": installdir.group(1),
            "dir": str(folder),
            "exists": folder.is_dir(),
        })
    return rows


def find_exe(folder: Path, game_name: str, limit: int = 6) -> str:
    """在游戏目录里挑一个最像「本体」的 exe（有限深度）。"""
    target = _norm(game_name)
    found: list[tuple[int, int, str]] = []   # (名字吻合度, 深度, 路径)
    stack: list[tuple[Path, int]] = [(folder, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if depth < MAX_DEPTH and entry.name.lower() not in SKIP_DIRS:
                        stack.append((entry, depth + 1))
                elif entry.is_file() and entry.suffix.lower() == ".exe" \
                        and entry.name.lower() not in SKIP_EXES:
                    stem = _norm(entry.stem)
                    score = 0
                    if stem and target:
                        if stem == target:
                            score = 3
                        elif stem in target or target in stem:
                            score = 2
                    found.append((score, -depth, str(entry)))
            except OSError:
                continue
    if not found:
        return ""
    # 名字吻合优先，其次层级更浅、路径更短
    found.sort(key=lambda row: (-row[0], -row[1], len(row[2])))
    return found[0][2]


def scan(existing_exes: set[str] | None = None) -> dict:
    """扫描所有 Steam 库，返回可导入的游戏列表。

    existing_exes 里的路径会被标记成 already=True（已经在库里了）。
    """
    known = {os.path.normcase(str(p)) for p in (existing_exes or set())}
    root = steam_root()
    if root is None:
        return {"ok": False, "error": "no-steam", "root": "", "libraries": [], "games": []}

    libraries = library_paths(root)
    games: list[dict] = []
    seen: set[str] = set()
    for library in libraries:
        for row in _manifests(library):
            if not row["exists"]:
                continue
            exe = find_exe(Path(row["dir"]), row["name"])
            if not exe or os.path.normcase(exe) in seen:
                continue
            seen.add(os.path.normcase(exe))
            games.append({
                "appid": row["appid"],
                "name": row["name"],
                "exe": exe,
                "exe_name": Path(exe).name,
                "dir": row["dir"],
                "library": str(library),
                "already": os.path.normcase(exe) in known,
            })
    games.sort(key=lambda row: row["name"].lower())
    return {
        "ok": True,
        "root": str(root),
        "libraries": [str(p) for p in libraries],
        "games": games,
    }
