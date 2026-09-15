"""Locale Emulator 转区启动。

只对接用户**本机已安装**的 Locale Emulator，不下载任何第三方程序。
调用契约（读 LE 源码确认）：

    LEProc.exe -runas <GUID> <游戏 exe> [参数…]     # 指定全局配置
    LEProc.exe -run <游戏 exe> [参数…]              # 用 LE 的默认配置

配置来自 LEProc.exe 同目录的 LEConfig.xml：<LEConfig><Profiles><Profile Name Guid>…
"""
from __future__ import annotations

import os
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

PROC_NAME = "LEProc.exe"
#: LE 运行需要的文件，缺一个就说明路径不对或安装不完整
REQUIRED_FILES = ("LEProc.exe", "LECommonLibrary.dll", "LoaderDll.dll", "LocaleEmulator.dll")
CONFIG_NAME = "LEConfig.xml"
DOWNLOAD_URL = "https://github.com/xupefei/Locale-Emulator/releases"
X86_MACHINE = 0x014C
X64_MACHINES = {0x8664: "x64", 0xAA64: "ARM64"}


# --------------------------------------------------------------------------- #
# 探测
# --------------------------------------------------------------------------- #
def candidate_dirs() -> list[Path]:
    """常见安装位置：环境变量目录 + 各盘符常见路径 + PATH。"""
    out: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
        root = os.environ.get(env_name)
        if root:
            out.append(Path(root) / "Locale Emulator")
    for drive in "CDEFGH":
        base = Path(f"{drive}:\\")
        try:
            if not base.exists():
                continue
        except OSError:
            continue
        out += [base / "Locale Emulator",
                base / "Program Files" / "Locale Emulator",
                base / "Program Files (x86)" / "Locale Emulator",
                base / "Tools" / "Locale Emulator",
                base / "Software" / "Locale Emulator"]
    found = shutil.which("LEProc") or shutil.which(PROC_NAME)
    if found:
        out.insert(0, Path(found).parent)
    return out


def validate(proc: str | Path | None) -> tuple[bool, str]:
    """校验 LEProc.exe 所在目录是否完整。"""
    if not proc:
        return False, "empty"
    path = Path(proc)
    if path.is_dir():
        path = path / PROC_NAME
    if path.name.lower() != PROC_NAME.lower():
        return False, "wrong-file"
    if not path.is_file():
        return False, "missing-proc"
    folder = path.parent
    for name in REQUIRED_FILES:
        if not (folder / name).is_file():
            return False, f"missing:{name}"
    return True, ""


def detect(saved: str = "") -> str:
    """返回可用的 LEProc.exe 路径；找不到返回空串。"""
    if saved:
        ok, _ = validate(saved)
        if ok:
            return str(Path(saved))
    for folder in candidate_dirs():
        ok, _ = validate(folder / PROC_NAME)
        if ok:
            return str(folder / PROC_NAME)
    return ""


def profiles(proc: str | Path | None) -> list[dict]:
    """读 LEConfig.xml 里的全局配置（供界面按名字选择）。"""
    if not proc:
        return []
    config = Path(proc).parent / CONFIG_NAME
    if not config.is_file():
        return []
    try:
        root = ET.parse(config).getroot()
    except Exception:
        return []
    rows: list[dict] = []
    for node in root.iter("Profiles"):
        for item in list(node):
            name = (item.get("Name") or "").strip()
            guid = (item.get("Guid") or "").strip()
            location = (item.findtext("Location") or "").strip()
            if not guid:
                continue
            rows.append({"name": name or location or guid, "guid": guid, "location": location})
    return rows


def pe_bits(path: str | Path) -> dict:
    """读 PE 头判断目标位数（LE 只支持 32 位目标，用于给提示）。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(0x40)
            if len(head) < 0x40 or head[:2] != b"MZ":
                return {"ok": False, "error": "not-pe"}
            offset = struct.unpack_from("<I", head, 0x3C)[0]
            fh.seek(offset)
            sig = fh.read(6)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if len(sig) < 6 or sig[:4] != b"PE\0\0":
        return {"ok": False, "error": "bad-header"}
    machine = struct.unpack_from("<H", sig, 4)[0]
    return {"ok": True, "machine": machine,
            "bits": 32 if machine == X86_MACHINE else 64,
            "arch": "x86" if machine == X86_MACHINE else X64_MACHINES.get(machine, "unknown")}


# --------------------------------------------------------------------------- #
# 启动命令
# --------------------------------------------------------------------------- #
def build_command(proc: str | Path, game_exe: str | Path, args: list[str] | None = None,
                  guid: str = "") -> list[str]:
    """拼出 LE 的启动命令（guid 为空 = 用 LE 默认配置）。"""
    head = [str(proc), "-runas", guid, str(game_exe)] if guid \
        else [str(proc), "-run", str(game_exe)]
    return head + [str(a) for a in (args or [])]


def status(saved: str = "") -> dict:
    """给设置界面用的状态。"""
    proc = detect(saved)
    rows = profiles(proc) if proc else []
    return {
        "available": bool(proc),
        "proc": proc,
        "saved": saved or "",
        "profiles": rows,
        "download_url": DOWNLOAD_URL,
    }
