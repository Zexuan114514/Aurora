"""逐个试 Textractor 的钩子名，看哪个能在目标游戏上出干净文本。

背景：少女之剑这类**改过的引擎 exe**（AdvHD_crack.exe）会让 Textractor 自带的
WillPlus 系列钩子失配（pattern not found），于是只剩按字形抓的 GDI 钩子，
文本就会缺字。这个脚本用来确认「还有没有别的钩子能拿到引擎原始文本」。

用法：
    python tools\\vntext_hookprobe.py --pid 26304 --advance 3
    python tools\\vntext_hookprobe.py --game 少女之剑 --names WillPlus,EmbedWillplus
输出：tools/vntext-hook-report.txt
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _common  # noqa: E402

_common.setup_console()

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SANDBOX = ROOT / "_sandbox" / "vntext-hookprobe"
REPORT = Path(__file__).resolve().parent / "vntext-hook-report.txt"
CREATE_NO_WINDOW = 0x08000000

#: Textractor 里与 galgame 文本相关的钩子名（先试引擎专用的，再试通用 GDI 的）
DEFAULT_NAMES = [
    "WillPlus", "WillPlusW", "WillPlusA", "WillPlus2", "EmbedWillplus",
    "EmbedWillplus3", "WillPlus3",
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="试钩子名")
    ap.add_argument("--game", default="")
    ap.add_argument("--exe", default="")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--names", default=",".join(DEFAULT_NAMES))
    ap.add_argument("--wait", type=float, default=3.0, help="每个钩子试多久")
    ap.add_argument("--advance", type=int, default=2, help="发钩子前先翻几页")
    return ap.parse_args()


ARGS = parse_args()
SANDBOX.mkdir(parents=True, exist_ok=True)
os.environ["AURORA_DATA"] = str(SANDBOX / "data")
(SANDBOX / "data").mkdir(parents=True, exist_ok=True)

from gl import locale, proctree, screencap, vntext, winapi  # noqa: E402
from vntext_advance import advance  # noqa: E402


def resolve() -> tuple[int, str]:
    if ARGS.pid:
        return int(ARGS.pid), ""
    exe = ARGS.exe
    if not exe:
        lib = _common.load_library()
        key = (ARGS.game or "").lower()
        for game in lib["games"]:
            if key and key in f"{game.get('name','')} {game.get('exe','')}".lower():
                exe = str(game.get("exe") or "")
                break
    if not exe:
        raise SystemExit("用 --game/--exe/--pid 指定目标")
    pids = sorted(proctree.matching_pids(exe))
    if not pids:
        raise SystemExit("游戏没在运行")
    return pids[0], exe


def main() -> int:
    pid, exe = resolve()
    cli = vntext.find_cli("")
    print(f"pid={pid} cli={cli} bits={locale.pe_bits(cli).get('bits')}")
    window = screencap.main_window(pid)
    if window:
        winapi.focus_window(int(window["hwnd"]))
        for _ in range(max(0, ARGS.advance)):
            time.sleep(1.5)
            print("翻页:", advance(int(window["hwnd"])))

    proc = subprocess.Popen([cli], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    proc.stdin.write(f"attach -P{pid}\n".encode("utf-16-le"))
    proc.stdin.flush()

    lines: list[tuple[float, str]] = []
    lock = threading.Lock()
    started = time.time()

    def reader(stream=None) -> None:
        stream = stream or proc.stdout      # 固定住这一根管子，重启 CLI 后别串线
        buf = bytearray()
        while True:
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
                text = raw.decode("utf-16-le", "ignore").rstrip("\r\n")
                with lock:
                    lines.append((time.time() - started, text))

    threading.Thread(target=reader, args=(proc.stdout,), daemon=True).start()

    report: list[str] = [f"钩子探测：pid={pid} exe={exe}", f"CLI：{cli}", ""]
    results: dict[str, list[str]] = {}

    def restart_cli() -> None:
        """TextractorCLI 收到不认识的钩子码会直接退出，换名字时得重新拉起来。"""
        nonlocal proc
        try:
            proc.terminate()
        except Exception:
            pass
        proc = subprocess.Popen([cli], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        proc.stdin.write(f"attach -P{pid}\n".encode("utf-16-le"))
        proc.stdin.flush()
        threading.Thread(target=reader, args=(proc.stdout,), daemon=True).start()
        time.sleep(3.0)

    for name in [n.strip() for n in ARGS.names.split(",") if n.strip()]:
        mark = len(lines)
        try:
            proc.stdin.write(f"{name} -P{pid}\n".encode("utf-16-le"))
            proc.stdin.flush()
        except Exception:
            print(f"--- {name}: CLI 已退出，重启后重试")
            restart_cli()
            try:
                proc.stdin.write(f"{name} -P{pid}\n".encode("utf-16-le"))
                proc.stdin.flush()
            except Exception as exc:
                print(f"    仍然失败：{exc}")
                continue
        time.sleep(ARGS.wait)
        with lock:
            new = [text for _, text in lines[mark:]]
        accepted = any("注入钩子" in row and name in row for row in new)
        bodies = [row for row in new
                  if "Textractor:" not in row and "vnreng" not in row
                  and not row.startswith("Usage")]
        results[name] = bodies
        print(f"--- {name}: {'已注入' if accepted else '（没看到注入回显）'} "
              f"新行 {len(new)} 条，正文 {len(bodies)} 条")
        for row in bodies[:4]:
            print("     ", row[:90])
        if window and bodies:
            time.sleep(1.0)
            advance(int(window["hwnd"]))
        report.append(f"[{name}] 注入回显={accepted} 新行={len(new)} 正文={len(bodies)}")
        for row in bodies[:8]:
            report.append(f"    {row[:120]}")
        for row in new:
            if "注入钩子" in row or "vnreng" in row or "error" in row.lower():
                report.append(f"    (控制台) {row[:120]}")
        if proc.poll() is not None:        # 这个钩子码把它搞崩了
            report.append(f"    (控制台) CLI 退出，退出码 {proc.returncode}")
            restart_cli()

    try:
        proc.stdin.write(f"detach -P{pid}\n".encode("utf-16-le"))
        proc.stdin.flush()
    except Exception:
        pass
    proc.terminate()
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print("\n报告：", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
