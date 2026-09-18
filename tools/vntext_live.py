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
    parser.add_argument("--translate-wait", type=float, default=45.0,
                        help="收完台词后等译文的最长时间")
    parser.add_argument("--keep-game", action="store_true", help="结束后不关闭游戏")
    parser.add_argument("--no-kill", action="store_true",
                        help="别清残留的 TextractorCLI（你自己开着启动器时用这个）")
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

from gl import (config, linetrans, locale, memmatch, proctree, screencap,  # noqa: E402
                vntext, winapi)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vntext_advance import advance  # noqa: E402  左键推进（空格在这类引擎里是隐藏文本框）


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


def _advance(hwnd: int) -> str:
    """先把游戏拉到前台，再左键点文本框（见 vntext_advance 模块注释）。"""
    winapi.focus_window(hwnd)
    time.sleep(0.25)
    return advance(hwnd)


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
    stale = 0 if ARGS.no_kill else kill_stale_cli()
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
    distinct: set[str] = set()
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
            distinct.add(vntext.normalize_for_dedupe(text))
        note(f"台词：{text}")
        if translator is not None:
            translator.submit(text, game_id=game_id, source=str(payload.get("source") or "hook"))
        # 「收到 N 句」按**不同的句子**算：OCR 模式下一屏会被反复识别，
        # 按条数算会让脚本刚抓到同一句就收工、一次都不翻页
        if len([row for row in distinct if row]) >= ARGS.want:
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
    engine_noise = set(getattr(engine, "_noise_names", ()))

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
                how = _advance(int(window["hwnd"]))
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
             f"gated={final.get('gated')} 引擎={status.get('engine_name')}")
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

    # 原始行 → 到底有没有变成台词：把「拿到文本但没识别出来」的行挑出来
    emitted_norms = [vntext.normalize_for_dedupe(row["text"]) for row in rows]
    audit = {"ok": 0, "empty": 0, "noise": 0, "fragment": 0, "missing": []}
    with lock:
        raw_snapshot = [row["text"] for row in raw_lines]
    # 缺字变体（Siglus 的 GDI 钩子会吐只剩汉字的同一句）会被引擎按设计并掉，
    # 审计要认得出来，别报成「漏掉」
    clean_all = [vntext.clean_hook_text(raw) for raw in raw_snapshot]
    long_rows = [row for row in clean_all if len(row) >= 6]
    for raw in raw_snapshot:
        clean = vntext.clean_hook_text(raw)
        if not clean:
            audit["empty"] += 1
            continue
        if vntext.looks_like_noise(clean) or vntext.norm_name(clean) in engine_noise:
            audit["noise"] += 1
            continue
        if not vntext.looks_like_dialogue(clean):
            # 打字中途的碎片（「そっ」「ちち」）会被线程门禁按设计丢掉，
            # 完整那句随后会从领跑线程正常出来 —— 不算漏
            audit["fragment"] += 1
            continue
        if clean.count("_") >= 3:
            # 资源表/场景名列表（Siglus 的 `うみ_0815rb40_うみ_0816rb40…`）
            audit["fragment"] += 1
            continue
        probe = vntext.collapse_doubling(clean)
        # 残片里可能夹着空格（实测 WillPlus 的 `真面絵描 約束違真似`），
        # 判定前先把空白压掉，否则会误报成「漏掉」
        bare = vntext._strip_ws(probe)
        if 2 <= len(bare) <= 24 and len(vntext.CJK_RE.findall(bare)) >= 2 \
                and any(len(vntext._strip_ws(old)) > len(bare)
                        and vntext.is_subsequence(bare, vntext._strip_ws(old))
                        for old in long_rows):
            audit["fragment"] += 1
            continue
        norm = vntext.normalize_for_dedupe(clean)
        hit = bool(norm) and any(norm == other or norm in other or other in norm
                                 for other in emitted_norms if other)
        if not hit:
            # 「缺字版→内存补全完整句」是现在的主力路径：残片不是完整句的子串，
            # 但它的字都在完整句里按顺序出现（注音残片用汉字档再比一次）
            hit = any(len(other) > len(clean)
                      and (vntext.is_subsequence(norm, other)
                           or bool(memmatch.kanji_span(norm, other)))
                      for other in emitted_norms if other)
        if hit:
            audit["ok"] += 1
        else:
            audit["missing"].append(clean)
            problems.append(f"原始行没被翻出来：{clean[:40]}")
    note(f"原始行审计：认出 {audit['ok']} 条 · 只有人名 {audit['empty']} 条 · "
         f"噪声 {audit['noise']} 条 · 半截碎片 {audit['fragment']} 条 · "
         f"**漏掉 {len(audit['missing'])} 条**")
    for item in audit["missing"][:6]:
        note(f"  ✗ 漏掉：{item}")

    _write_report(game, status, raw_lines, rows, notes, problems, pids, modules, audit)
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
                  modules: list[str] | None = None, audit: dict | None = None) -> None:
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
    if audit:
        lines.append(f"原始行审计：认出 {audit['ok']} / 只有人名 {audit['empty']} / "
                     f"噪声 {audit['noise']} / 半截碎片 {audit['fragment']} / "
                     f"漏掉 {len(audit['missing'])}")
        for item in audit["missing"]:
            lines.append(f"  ✗ 漏掉：{item}")
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
