"""把 TextractorCLI 吐出来的每一行原样 dump 出来（不做合并、不做过滤）。

用途：查「某个引擎为什么缺字 / 哪条线程才是完整文本」这类问题。
和 vntext_live.py 的区别：那个跑的是启动器真实链路（含清洗与翻译），
这个只是把钩子的原始流摊开看。

用法：
    python tools\\vntext_rawdump.py --game 少女之剑 --seconds 60 --advance 8
    python tools\\vntext_rawdump.py --pid 7844 --seconds 40 --keep-game
输出：tools/vntext-raw-report.txt（含每条线程的汇总：hook 名、地址、样例）
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox" / "vntext-raw"
REPORT = Path(__file__).resolve().parent / "vntext-raw-report.txt"
CREATE_NO_WINDOW = 0x08000000
VK_SPACE = 0x20

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]
user32.GetForegroundWindow.restype = wintypes.HWND


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="转储 TextractorCLI 原始输出")
    ap.add_argument("--game", default="", help="按游戏名从库里找 exe")
    ap.add_argument("--exe", default="", help="直接给 exe 路径")
    ap.add_argument("--pid", type=int, default=0, help="直接给进程号（不启动游戏）")
    ap.add_argument("--cli", default="", help="TextractorCLI.exe 路径（默认取设置/自动探测）")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--advance", type=int, default=0, help="自动翻页次数")
    ap.add_argument("--advance-gap", type=float, default=4.0)
    ap.add_argument("--keep-game", action="store_true")
    return ap.parse_args()


ARGS = parse_args()
SANDBOX.mkdir(parents=True, exist_ok=True)
os.environ["AURORA_DATA"] = str(SANDBOX / "data")
(SANDBOX / "data").mkdir(parents=True, exist_ok=True)

from gl import locale, proctree, screencap, vntext, winapi  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vntext_advance import advance  # noqa: E402

LINE_RE = re.compile(
    r"^\[([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]*):?"
    r"([^\]:]*):?([^\]]*)\]\s?(.*)$")


def resolve_target() -> tuple[int, str]:
    if ARGS.pid:
        from gl import process as process_mod

        return int(ARGS.pid), process_mod.process_image(int(ARGS.pid))
    exe = ARGS.exe
    if not exe:
        library = json.loads((ROOT / "data" / "library.json").read_text(encoding="utf-8"))
        key = (ARGS.game or "").lower()
        for game in library["games"]:
            if key and key in f"{game.get('name','')} {game.get('exe','')}".lower():
                exe = str(game.get("exe") or "")
                break
    if not exe:
        raise SystemExit("没找到游戏，用 --exe 或 --pid 指定")
    pids = sorted(proctree.matching_pids(exe))
    if not pids:
        raise SystemExit(f"{exe} 没在运行（先用启动器或 vntext_live.py 起一个）")
    return pids[0], exe


def rows_of(text: str) -> dict:
    match = LINE_RE.match(text.rstrip("\r\n"))
    if not match:
        return {"thread": "", "name": "", "code": "", "text": text.strip()}
    handle, pid, addr, ctx, ctx2, name, code, body = match.groups()
    return {"thread": f"{handle}:{pid}:{addr}:{ctx}:{ctx2}", "name": name,
            "code": code, "text": body.strip()}


def main() -> int:
    pid, exe = resolve_target()
    cli = ARGS.cli or vntext.find_cli("")
    if not cli:
        raise SystemExit("找不到 TextractorCLI.exe")
    print(f"目标 pid={pid} exe={exe}")
    print("CLI:", cli, "位数", locale.pe_bits(cli).get("bits"))
    window = screencap.main_window(pid)
    print("窗口:", window)

    for row in proctree.snapshot():
        if row["name"].lower() == "textractorcli.exe":
            subprocess.run(["taskkill", "/PID", str(row["pid"]), "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)

    proc = subprocess.Popen([cli], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    proc.stdin.write(f"attach -P{pid}\n".encode("utf-16-le"))
    proc.stdin.flush()

    records: list[dict] = []
    threads: "OrderedDict[str, dict]" = OrderedDict()
    started = time.time()
    advances = 0
    next_advance = started + 12.0
    # 读取必须放线程里：管子里没数据时 read1 会阻塞，主线程就轮不到翻页和收工
    queue: list[dict] = []
    queue_lock = threading.Lock()

    def reader() -> None:
        buf = bytearray()
        stream = proc.stdout
        while stream is not None:
            try:
                chunk = stream.read1(4096)
            except Exception:
                return
            if not chunk:
                return
            buf += chunk
            while True:
                cut = buf.find(b"\n\x00")
                if cut < 0:
                    break
                raw = bytes(buf[:cut + 1])
                del buf[:cut + 2]
                row = rows_of(raw.decode("utf-16-le", "ignore"))
                if not row["text"]:
                    continue
                row["at"] = time.time() - started
                with queue_lock:
                    queue.append(row)

    threading.Thread(target=reader, daemon=True, name="rawdump-reader").start()
    while time.time() - started < ARGS.seconds:
        time.sleep(0.2)
        with queue_lock:
            pending, queue[:] = list(queue), []
        for row in pending:
            records.append(row)
            key = row["thread"] or "(无)"
            info = threads.setdefault(key, {"name": row["name"], "code": row["code"],
                                            "count": 0, "samples": []})
            info["count"] += 1
            if row["name"]:
                info["name"] = row["name"]
            if row["code"]:
                info["code"] = row["code"]
            if len(info["samples"]) < 6 and row["text"] not in info["samples"]:
                info["samples"].append(row["text"][:90])
            if "Textractor:" not in row["text"] and "vnreng" not in row["text"]:
                print(f"[{row['at']:6.1f}] {key[:26]:26s} {row['name'][:34]:34s} "
                      f"{row['text'][:70]}", flush=True)
        if window and ARGS.advance and advances < ARGS.advance \
                and time.time() >= next_advance:
            winapi.focus_window(int(window["hwnd"]))
            time.sleep(0.2)
            how = advance(int(window["hwnd"]))
            print(f"--- 翻页 {advances + 1}/{ARGS.advance}：{how or '窗口不在前台'} ---",
                  flush=True)
            advances += 1
            next_advance = time.time() + ARGS.advance_gap

    try:
        proc.stdin.write(f"detach -P{pid}\n".encode("utf-16-le"))
        proc.stdin.flush()
    except Exception:
        pass
    proc.terminate()
    if not ARGS.keep_game and not ARGS.pid:
        for target in proctree.matching_pids(exe):
            subprocess.run(["taskkill", "/PID", str(target), "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)

    lines: list[str] = []
    lines.append("Textractor 原始输出 dump")
    lines.append(f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}  pid={pid}  exe={exe}")
    lines.append(f"CLI：{cli}  时长：{ARGS.seconds}s  翻页：{advances} 次")
    lines.append("")
    lines.append(f"=== 线程汇总（{len(threads)} 条）===")
    for key, info in threads.items():
        lines.append(f"[{key}] name={info['name']} code={info['code']} 行数={info['count']}")
        for sample in info["samples"]:
            lines.append(f"    {sample}")
    lines.append("")
    lines.append(f"=== 全部原始行（{len(records)} 条）===")
    for row in records:
        lines.append(f"[{row['at']:7.2f}] {row['thread']} | {row['name']} | {row['code']}"
                     f" | {row['text']}")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告：{REPORT}（线程 {len(threads)} 条，原始行 {len(records)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
