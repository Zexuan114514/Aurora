"""游戏内翻译真机自测：启动游戏 → 挂 Textractor → 收真实台词 → 清洗 → 翻译。

和 vntext_probe.py（假 CLI 的离线用例）互补：这条链路跑的是**真实游戏 +
真实 TextractorCLI**，用来回答「三形态文本到底洗干净了没有」。

用法（在项目根目录执行）：
    python tools/vntext_live.py                     # 默认 DRACU-RIOT!
    python tools/vntext_live.py --advance 8         # 自动往前翻 8 句
    python tools/vntext_live.py --game 少女之剑 --mode ocr
    python tools/vntext_live.py --no-launch         # 游戏已经在跑，只挂钩子
    python tools/vntext_live.py --live-data         # 直接用真实 data/（会写会话记录）

结果写到 tools/vntext-live-report.txt；全部断言通过时退出码 0。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox" / "vntext-live"
REPORT = Path(__file__).resolve().parent / "vntext-live-report.txt"

VK_SPACE = 0x20
VK_RETURN = 0x0D
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t,
                                ctypes.c_ssize_t]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="游戏内翻译真机自测")
    parser.add_argument("--game", default="DRACU", help="游戏名或 exe 关键字")
    parser.add_argument("--exe", default="", help="直接指定游戏 exe（优先于 --game）")
    parser.add_argument("--mode", default="", choices=["", "auto", "hook", "ocr"])
    parser.add_argument("--seconds", type=float, default=150.0, help="最长观察时间")
    parser.add_argument("--want", type=int, default=5, help="希望收集到的台词条数")
    parser.add_argument("--advance", type=int, default=6, help="最多自动翻页次数")
    parser.add_argument("--advance-gap", type=float, default=3.0)
    parser.add_argument("--no-launch", action="store_true", help="不启动游戏，只挂已在跑的")
    parser.add_argument("--live-data", action="store_true", help="用真实 data/ 目录")
    parser.add_argument("--no-translate", action="store_true", help="只测文本，不调翻译接口")
    parser.add_argument("--translate-wait", type=float, default=25.0,
                        help="收完台词后等译文的最长时间")
    parser.add_argument("--keep-game", action="store_true", help="结束后不关闭游戏")
    return parser.parse_args()


def prepare_data(live: bool) -> Path:
    """默认在沙盒里跑：复制真实库（含设置）过去，别污染用户的会话记录。"""
    if live:
        return ROOT / "data"
    data = SANDBOX / "data"
    data.mkdir(parents=True, exist_ok=True)
    source = ROOT / "data" / "library.json"
    if not source.is_file():
        raise SystemExit(f"找不到 {source}")
    shutil.copy2(source, data / "library.json")
    return data


ARGS = parse_args()
DATA = prepare_data(ARGS.live_data)
os.environ["AURORA_DATA"] = str(DATA)

from gl import config, linetrans, locale, proctree, screencap, vntext, winapi  # noqa: E402


def load_library() -> dict:
    return json.loads((DATA / "library.json").read_text(encoding="utf-8"))


def pick_game(library: dict) -> dict:
    if ARGS.exe:
        needle = os.path.normcase(ARGS.exe)
        for game in library["games"]:
            if os.path.normcase(str(game.get("exe") or "")) == needle:
                return game
        return {"id": "adhoc", "name": Path(ARGS.exe).stem, "exe": ARGS.exe,
                "locale_enabled": False, "locale_guid": ""}
    key = ARGS.game.lower()
    for game in library["games"]:
        hay = f"{game.get('name','')} {game.get('exe','')}".lower()
        if key in hay:
            return game
    raise SystemExit(f"库里没有匹配「{ARGS.game}」的游戏（--game 换个关键字）")


def kill_stale_cli() -> int:
    """清掉上次残留的 TextractorCLI（否则 attach 会打架）。"""
    rows = proctree.snapshot()
    killed = 0
    for row in rows:
        if row["name"].lower() != "textractorcli.exe":
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(row["pid"]), "/F"],
                           capture_output=True, creationflags=0x08000000)
            killed += 1
        except Exception:
            pass
    return killed


def wait_pids(exe: str, timeout: float) -> list[int]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        pids = sorted(proctree.matching_pids(exe))
        if pids:
            return pids
        time.sleep(0.5)
    return []


def launch_game(game: dict, settings: dict, note) -> tuple[list[int], str]:
    """按多种方式依次尝试启动，直到进程真的出现。"""
    exe = str(game.get("exe") or "")
    if not Path(exe).is_file():
        raise SystemExit(f"游戏 exe 不存在：{exe}")
    pids = sorted(proctree.matching_pids(exe))
    if pids:
        note(f"游戏已在运行 pid={pids}")
        return pids, "已运行"

    attempts: list[tuple[str, list[str] | None]] = []
    le_proc = locale.detect(str(settings.get("le_proc_path") or ""))
    if game.get("locale_enabled") and le_proc and Path(exe).suffix.lower() == ".exe":
        guid = str(game.get("locale_guid") or "")
        attempts.append(("locale-emulator", locale.build_command(le_proc, exe, guid=guid)))
    attempts.append(("direct", [exe]))
    attempts.append(("startfile", None))
    attempts.append(("cmd-start", [os.environ.get("ComSpec", "cmd.exe"), "/c", "start", "",
                                    exe]))

    for name, cmd in attempts:
        note(f"尝试启动方式：{name}")
        try:
            if cmd is None:
                os.startfile(exe)                       # noqa: S606 - 用户自己的游戏
            else:
                subprocess.Popen(cmd, cwd=str(Path(exe).parent), close_fds=True,
                                 creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        except Exception as exc:
            note(f"  启动失败：{exc}")
            continue
        pids = wait_pids(exe, 25.0)
        if pids:
            note(f"  进程已创建 pid={pids}")
            return pids, name
        note("  25s 内没看到进程，换下一种方式")
    return [], ""


def advance(hwnd: int, key: int) -> str:
    """让游戏往前翻一句；返回用了哪种方式（空串 = 都没成功）。"""
    if not hwnd:
        return ""
    # 1) 能拿到前台就用真实按键（最通用）
    winapi.focus_window(hwnd)
    time.sleep(0.25)
    try:
        if int(user32.GetForegroundWindow() or 0) == int(hwnd):
            user32.keybd_event(key, 0, 0, None)
            time.sleep(0.05)
            user32.keybd_event(key, 0, 2, None)      # KEYEVENTF_KEYUP
            return "前台按键"
    except Exception:
        pass
    # 2) 拿不到前台（Windows 会拒绝后台进程抢焦点）就投递窗口消息：
    #    TVP/KIRIKIRI 在 WndProc 里收键盘/鼠标消息，PostMessage 也能翻页，
    #    而且不会影响到别的窗口。
    try:
        if user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYDOWN, key, 0):
            user32.PostMessageW(wintypes.HWND(hwnd), WM_KEYUP, key, 0)
            return "窗口消息"
    except Exception:
        pass
    try:
        rect = wintypes.RECT()
        user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        point = ((rect.right // 2) & 0xFFFF) | (((rect.bottom * 4 // 5) & 0xFFFF) << 16)
        user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONDOWN, 1, point)
        user32.PostMessageW(wintypes.HWND(hwnd), WM_LBUTTONUP, 0, point)
        return "窗口点击"
    except Exception:
        return ""


def main() -> int:
    library = load_library()
    settings = library.get("settings") or {}
    game = pick_game(library)
    game_id = str(game.get("id") or "")
    exe = str(game.get("exe") or "")
    notes: list[str] = []

    def note(text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        notes.append(line)
        print(line, flush=True)

    note(f"目标游戏：{game.get('name')} ({exe})")
    stale = kill_stale_cli()
    note(f"清理残留 TextractorCLI：{stale} 个")

    if ARGS.no_launch:
        pids = sorted(proctree.matching_pids(exe))
        method = "已运行"
        if not pids:
            raise SystemExit("--no-launch 但游戏进程不存在")
    else:
        pids, method = launch_game(game, settings, note)
        if not pids:
            note("四种启动方式都没能创建进程 —— 请手动启动一次再看看")
            _write_report(game, {}, [], [], notes, ["游戏进程没能启动"], [])
            return 2
    pid = pids[0]
    note(f"游戏进程 pid={pid} bits={locale.pe_bits(exe).get('bits')}")
    modules = vntext.module_names(pid)
    note(f"进程模块 {len(modules)} 个：" +
         ", ".join(Path(name).name for name in modules[:14]))

    window = None
    for _ in range(40):
        window = screencap.main_window(pid) or screencap.main_window(pids[-1])
        if window:
            break
        time.sleep(0.5)
    note(f"游戏窗口：{window}")

    raw_lines: list[dict] = []
    lines: list[dict] = []
    results: list[dict] = []
    lock = threading.Lock()
    done = threading.Event()

    translator = None
    if not ARGS.no_translate:
        def on_event(kind: str, payload: dict) -> None:
            if kind == "done":
                with lock:
                    for row in results:
                        if row["text"] == payload.get("text") and not row["translation"]:
                            row["translation"] = payload.get("translation", "")
                            row["provider"] = payload.get("provider", "")
                            break
            elif kind == "error":
                note(f"翻译失败：{payload.get('error')} ← {payload.get('text','')[:24]}")

        translator = linetrans.LineTranslator(settings_getter=lambda: settings,
                                              on_event=on_event)

    def on_raw(payload: dict) -> None:
        with lock:
            raw_lines.append(payload)

    def on_line(payload: dict) -> None:
        text = str(payload.get("text") or "")
        row = {"text": text, "source": payload.get("source", ""),
               "at": time.time(), "artifacts": vntext.residual_artifacts(text),
               "translation": "", "provider": ""}
        with lock:
            results.append(row)
            lines.append(payload)
        note(f"台词：{text}")
        if translator is not None:
            translator.submit(text, game_id=game_id, source=str(payload.get("source") or "hook"))
        if len(results) >= ARGS.want:
            done.set()

    engine = vntext.VnTextEngine(settings_getter=lambda: settings, on_line=on_line,
                                 on_status=lambda state: None, on_raw=on_raw)
    mode = ARGS.mode or str(settings.get("vntext_engine") or "auto")
    status = engine.start(game_id, pid, mode=mode, exe=exe)
    note(f"文本源：mode={status.get('engine')} 引擎={status.get('engine_name')} "
         f"cli={status.get('cli')} bits={status.get('cli_bits')}/"
         f"{status.get('target_bits')} error={status.get('error')}")
    note(f"候选进程：{status.get('probe', {}).get('targets')}")
    if status.get("hook_hint"):
        note(f"引擎建议：{status['hook_hint']}")

    started = time.time()
    advances = 0
    next_advance = started + 6.0
    try:
        while not done.is_set() and time.time() - started < ARGS.seconds:
            time.sleep(0.5)
            with lock:
                got = len(results)
            if got >= ARGS.want:
                break
            if window and advances < ARGS.advance and time.time() >= next_advance:
                how = advance(int(window["hwnd"]), VK_SPACE)
                advances += 1
                next_advance = time.time() + ARGS.advance_gap
                note(f"自动翻页 {advances}/{ARGS.advance}（{how or '没能送出'}）")
    finally:
        # 等译文回来（免费接口偶尔慢，别刚收完台词就收工）
        deadline = time.time() + ARGS.translate_wait
        while time.time() < deadline:
            with lock:
                pending = [row for row in results if not row["translation"]]
            if not pending:
                break
            time.sleep(1.0)
        final = engine.stop()
        status = engine.status()               # 收工时的状态（引擎标识可能后到）
        note(f"停止文本源：lines={final.get('lines')} merged={final.get('merged')} "
             f"引擎={status.get('engine_name')}")
        if not ARGS.keep_game:
            for target in pids:
                try:
                    subprocess.run(["taskkill", "/PID", str(target), "/F"],
                                   capture_output=True, creationflags=0x08000000)
                except Exception:
                    pass
            note("已关闭游戏进程（--keep-game 可保留）")

    with lock:
        rows = list(results)

    problems: list[str] = []
    if len(rows) < 3:
        problems.append(f"只收到 {len(rows)} 条台词（要求 ≥3）")
    for row in rows:
        if row["artifacts"]:
            problems.append(f"仍有重复痕迹 {row['artifacts']}：{row['text'][:40]}")
    norms = [vntext.normalize_for_dedupe(row["text"]) for row in rows]
    for index in range(1, len(norms)):
        if norms[index] and norms[index] == norms[index - 1]:
            problems.append(f"相邻重复台词：{rows[index]['text'][:40]}")
    if not ARGS.no_translate:
        missing = [row["text"][:30] for row in rows if not row["translation"]]
        if len(missing) == len(rows) and rows:
            problems.append("一条译文都没回来（检查网络 / 翻译设置）")
        elif missing:
            problems.append(f"{len(missing)} 条没等到译文：{missing}")
    if status.get("engine_name") in ("", "unknown"):
        problems.append("引擎标识仍为 unknown")
    if status.get("error"):
        problems.append(f"文本源报错：{status['error']}")

    _write_report(game, status, raw_lines, rows, notes, problems, pids, modules)
    print("\n=== 结论 ===")
    if problems:
        for item in problems:
            print(f"  ✗ {item}")
        print(f"报告：{REPORT}")
        return 1
    print(f"  ✓ {len(rows)} 条台词全部干净，译文 {sum(1 for r in rows if r['translation'])} 条")
    print(f"报告：{REPORT}")
    return 0


def _write_report(game: dict, status: dict, raw_lines: list[dict], rows: list[dict],
                  notes: list[str], problems: list[str], pids: list[int],
                  modules: list[str] | None = None) -> None:
    lines: list[str] = []
    lines.append("Aurora 游戏内翻译 · 真机自测报告")
    lines.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"游戏：{game.get('name')}  exe={game.get('exe')}  pid={pids}")
    lines.append(f"文本源：mode={status.get('engine')} 引擎={status.get('engine_name')} "
                 f"cli={status.get('cli')} error={status.get('error')}")
    lines.append("进程模块：")
    for name in (modules or [])[:40]:
        lines.append(f"  {name}")
    lines.append("")
    lines.append(f"结论：{'全部通过' if not problems else '有问题'}")
    for item in problems:
        lines.append(f"  ✗ {item}")
    lines.append("")
    lines.append(f"--- 原始钩子行（{len(raw_lines)} 条）---")
    for row in raw_lines:
        lines.append(f"[{row.get('thread','')}] name={row.get('name','')} "
                     f"code={row.get('code','')}")
        lines.append(f"    {row.get('text','')}")
    lines.append("")
    lines.append(f"--- 清洗后的台词 + 译文（{len(rows)} 条）---")
    for row in rows:
        lines.append(f"原文：{row['text']}")
        lines.append(f"译文：{row['translation'] or '（无）'}  [{row['provider']}] "
                     f"artifacts={row['artifacts']}")
        lines.append("")
    lines.append("--- 过程日志 ---")
    lines.extend(notes)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
