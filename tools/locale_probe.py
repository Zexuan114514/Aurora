"""转区启动自检：LE 探测 / 四件套校验 / 配置解析 / 启动命令 / PE 位数。

只对接本机**已安装**的 Locale Emulator；本机没装也要能跑通过（走「未安装」分支，
只要 `_locale_command` 老老实实返回 no-le，而不是抛异常或硬启动）。
结果写入 tools/locale-report.txt。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import io
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox"
TEST_DATA = SANDBOX / "locale-data"
FAKE_LE = SANDBOX / "locale-fake" / "Locale Emulator"
BROKEN_LE = SANDBOX / "locale-fake" / "Broken LE"
REPORT = Path(__file__).resolve().parent / "locale-report.txt"

GUID = "{11111111-1111-1111-1111-111111111111}"
GAME_EXE = r"C:\games\jp\otonari.exe"

os.environ["AURORA_DATA"] = str(TEST_DATA)

from gl import locale  # noqa: E402
from gl.api import Api  # noqa: E402

LE_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<LEConfig>
  <Profiles>
    <Profile Name="&#26085;&#26412;&#35486; (&#26085;&#26412;)" Guid="{11111111-1111-1111-1111-111111111111}">
      <Parameter />
      <Location>ja-JP</Location>
      <Timezone>Tokyo Standard Time</Timezone>
    </Profile>
    <Profile Name="&#32321;&#39636;&#20013;&#25991;" Guid="{22222222-2222-2222-2222-222222222222}">
      <Location>zh-TW</Location>
    </Profile>
    <Profile Name="no-guid-profile" />
  </Profiles>
</LEConfig>
"""


def build_fixtures() -> None:
    FAKE_LE.mkdir(parents=True, exist_ok=True)
    for name in locale.REQUIRED_FILES:
        path = FAKE_LE / name
        if not path.exists():
            # 最小 MZ 头：够 validate() 通过，又会让 PE 解析走到 bad-header
            path.write_bytes(b"MZ" + b"\0" * 62)
    (FAKE_LE / locale.CONFIG_NAME).write_text(LE_CONFIG, encoding="utf-8")

    BROKEN_LE.mkdir(parents=True, exist_ok=True)
    for name in locale.REQUIRED_FILES:
        if name == "LoaderDll.dll":
            continue
        target = BROKEN_LE / name
        if not target.exists():
            shutil.copy2(FAKE_LE / name, target)


def main() -> int:
    out = io.StringIO()

    def write(line: str = "") -> None:
        out.write(line + "\n")

    def check(label: str, ok: bool, detail="") -> bool:
        nonlocal failed
        if not ok:
            failed += 1
        write(f"  {'OK ' if ok else 'BAD'} {label}" + (f"  {detail}" if detail else ""))
        return ok

    failed = 0
    # 每次从干净的数据目录开始：上次探测写进去的 le_proc_path 会把「未安装」分支带偏
    shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)
    build_fixtures()

    write("Aurora 转区启动自检")
    write("=" * 52)

    live = locale.status("")
    write("\n[本机 Locale Emulator]")
    write(f"  {'已安装：' + live['proc'] if live['available'] else '未安装（下面用伪造目录测逻辑）'}")
    write(f"  候选目录数：{len(locale.candidate_dirs())}")

    write("\n[四件套校验]")
    ok, err = locale.validate(FAKE_LE / locale.PROC_NAME)
    check("完整目录通过校验", ok, err)
    bad, bad_err = locale.validate(BROKEN_LE / locale.PROC_NAME)
    check("缺 LoaderDll.dll 必须判失败", (not bad) and bad_err == "missing:LoaderDll.dll", bad_err)
    empty, empty_err = locale.validate("")
    check("空路径判失败", (not empty) and empty_err == "empty", empty_err)
    wrong, wrong_err = locale.validate(FAKE_LE / "notLE.exe")
    check("文件名不对判失败", (not wrong) and wrong_err == "wrong-file", wrong_err)
    check("detect() 能识别指定路径", locale.detect(str(FAKE_LE / locale.PROC_NAME))
          == str(FAKE_LE / locale.PROC_NAME))

    write("\n[LEConfig.xml 解析]")
    rows = locale.profiles(FAKE_LE / locale.PROC_NAME)
    check("读到两条带 Guid 的配置", len(rows) == 2, f"{len(rows)} 条："
          + " / ".join(r["name"] for r in rows))
    check("无 Guid 的条目被跳过", all(r.get("guid") for r in rows))
    check("配置名与区域都对", bool(rows) and rows[0]["guid"] == GUID
          and rows[0]["location"] == "ja-JP")

    write("\n[启动命令]")
    proc = str(FAKE_LE / locale.PROC_NAME)
    cmd = locale.build_command(proc, GAME_EXE, ["-n", "5"], guid=GUID)
    want = [proc, "-runas", GUID, GAME_EXE, "-n", "5"]
    check("指定配置 -> -runas <GUID>", cmd == want, " ".join(cmd))
    cmd2 = locale.build_command(proc, GAME_EXE)
    check("未指定配置 -> -run", cmd2 == [proc, "-run", GAME_EXE], " ".join(cmd2))

    write("\n[PE 位数]")
    sys32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "ping.exe"
    wow64 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "SysWOW64" / "ping.exe"
    if sys32.is_file():
        info = locale.pe_bits(sys32)
        check("System32 的 exe 判为 64 位", info.get("bits") == 64, str(info))
    if wow64.is_file():
        info = locale.pe_bits(wow64)
        check("SysWOW64 的 exe 判为 32 位", info.get("bits") == 32, str(info))
    fake = locale.pe_bits(FAKE_LE / locale.PROC_NAME)
    check("非 PE 文件不误判", fake.get("ok") is False, str(fake))

    write("\n[api._locale_command]")
    api = Api()
    try:
        game = api._library.add({
            "id": "locale-probe", "name": "probe", "exe": GAME_EXE,
            "locale_enabled": True, "locale_guid": GUID,
        })
        detected = locale.detect("")
        launcher, note = api._locale_command(game)
        if detected:
            check("本机已装 LE：走 LE 启动", bool(launcher) and launcher[0] == detected,
                  f"{note} | {' '.join(launcher or [])}")
        else:
            check("未装 LE：返回 no-le 且不拼命令", launcher is None and note == "no-le", note)

        api.set_locale_option("le_proc_path", proc)
        game = api._library.get("locale-probe")
        launcher, note = api._locale_command(game)
        check("指定伪造 LE 后按 -runas 启动",
              bool(launcher) and launcher[:3] == [proc, "-runas", GUID], f"{note} | {launcher}")

        game["exe"] = r"C:\games\jp\boot.bat"
        launcher, note = api._locale_command(game)
        check("目标不是 exe：返回 unsupported-target",
              launcher is None and note == "unsupported-target", note)

        game["locale_enabled"] = False
        game["exe"] = GAME_EXE
        launcher, note = api._locale_command(game)
        check("没开转区的游戏不拼命令", launcher is None and note == "", note)

        st = api.get_locale_status()
        check("设置页拿到完整状态",
              st.get("ok") and st.get("available") and st.get("proc") == proc
              and len(st.get("profiles") or []) == 2,
              f"available={st.get('available')} profiles={len(st.get('profiles') or [])}")
    finally:
        api._downloads.stop()

    write("\n结论: " + ("全部通过" if not failed else f"{failed} 项失败"))
    text = out.getvalue()
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
