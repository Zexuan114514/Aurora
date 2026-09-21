"""钩子查找器自检：H-code 生成 + 调试器链路（合成目标进程）+ 失败路径。

合成目标做的事：在固定地址分配一段 UTF-16 文本，再执行一小段**自己写的机器码**：
    push rcx        ; 把缓冲区指针压栈
    mov rax,[rsp]   ; 从栈上读回（这一步保证栈槽里确实留着指针）
    movzx eax,word [rax]   ; ← 断点会在这里命中
    add rsp,8 ; ret
这样「访问指令 + 栈槽偏移」都可预期：偏移应当是 0（指针就在 ESP 处）。
结果写入 tools/hooksearch-report.txt。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox" / "hooksearch"
REPORT = Path(__file__).resolve().parent / "hooksearch-report.txt"
os.environ.setdefault("AURORA_DATA", str(SANDBOX / "data"))
(SANDBOX / "data").mkdir(parents=True, exist_ok=True)

from gl import hookfinder  # noqa: E402

TARGET_SRC = '''
import ctypes, sys, time

k32 = ctypes.WinDLL("kernel32")
k32.VirtualAlloc.restype = ctypes.c_void_p
k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong,
                             ctypes.c_ulong]

buf = k32.VirtualAlloc(ctypes.c_void_p(0x20000000), 4096, 0x1000 | 0x2000, 0x04)
text = "テスト台詞です".encode("utf-16-le")
ctypes.memmove(buf, text, len(text))

stub = k32.VirtualAlloc(ctypes.c_void_p(0x21000000), 4096, 0x1000 | 0x2000, 0x40)
code = bytes.fromhex("51") + bytes.fromhex("488b0424") + bytes.fromhex("0fb700") \\
    + bytes.fromhex("4883c408") + bytes.fromhex("c3")
ctypes.memmove(stub, code, len(code))
fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(stub)

print("%d %d" % (buf, stub), flush=True)
while True:
    fn(ctypes.c_void_p(buf))
    time.sleep(0.005)
'''


def main() -> int:
    lines: list[str] = []
    failed = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        if not ok:
            failed += 1
        text = f"  {'OK ' if ok else 'BAD'} {label}" + (f"  {detail}" if detail else "")
        print(text, flush=True)
        lines.append(text)

    lines.append("Aurora 钩子查找器自检")
    lines.append("=" * 52)

    # ---------------------------------------------------------------- H-code
    lines.append("\n[H-code 生成（拿两条真机实测码当基准）]")
    got = hookfinder.build_code(module="Amakano3.exe", module_base=0x140000000,
                                rip=0x1401B1F70, offset=-0x70, encoding="utf-8")
    check("アマカノ３ 实测码能复现",
          got == "HS65001#-6C@1B1F70:Amakano3.exe", got)
    got = hookfinder.build_code(module="AdvHD_crack.exe", module_base=0x400000,
                                rip=0x40A22E, offset=-8, encoding="utf-16")
    check("少女之剑 实测码能复现", got == "HQ-4@A22E:AdvHD_crack.exe", got)
    got = hookfinder.build_code(module="x.exe", module_base=0x400000, rip=0x401000,
                                offset=-0x10, padding=2, encoding="utf-8")
    check("正/负偏移与 padding 写法", got == "HS65001#2+-C@1000:x.exe", got)
    try:
        hookfinder.build_code(module="x.exe", module_base=0x500000, rip=0x400000,
                              offset=0)
        check("地址不在模块内时报错", False, "没报错")
    except hookfinder.HookFinderError as exc:
        check("地址不在模块内时报错", exc.reason == "bad-address", exc.reason)

    # ------------------------------------------------------ 合成目标进程
    lines.append("\n[调试器链路（合成目标进程）]")
    target = SANDBOX / "target.py"
    target.write_text(TARGET_SRC, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(target)], stdout=subprocess.PIPE,
                            text=True)
    try:
        head = proc.stdout.readline().strip().split()
        buf_addr, stub_addr = int(head[0]), int(head[1])
        check("目标进程已就绪", buf_addr > 0 and stub_addr > 0,
              f"buf={hex(buf_addr)} stub={hex(stub_addr)}")

        buffers = hookfinder.locate_buffers(proc.pid, "テスト台詞です")
        hit_addr = {row["address"] for row in buffers}
        check("能在目标进程内存里定位文本缓冲区",
              any(row["address"] == buf_addr for row in buffers),
              str([hex(row["address"]) for row in buffers[:3]]))
        check("定位结果带编码信息",
              any(row["encoding"] == "utf-16" for row in buffers),
              str(buffers[:2]))

        result = hookfinder.search(proc.pid, [{"address": buf_addr, "encoding": "utf-16"}],
                                   seconds=4.0)
        rows = result.get("hits") or []
        check("断点命中并生成候选", bool(rows),
              f"reason={result.get('reason')} hits={len(rows)}")
        offsets = {row["offset"] for row in rows}
        check("栈槽偏移正确（指针就在 ESP 处 → 0）",
              any(abs(off) <= 8 for off in offsets), str(sorted(offsets)[:6]))
        code = hookfinder.build_code(module="target.exe", module_base=0x21000000,
                                     rip=rows[0]["rip"], offset=rows[0]["offset"],
                                     padding=rows[0]["padding"],
                                     encoding=rows[0]["encoding"]) if rows else ""
        check("能拼出候选 H-code", bool(code) and code.startswith("H"), code)

        time.sleep(0.5)
        alive = proc.poll() is None
        check("查找结束后目标进程仍然存活（已正确分离调试器）", alive,
              f"poll={proc.poll()}")
    finally:
        try:
            proc.kill()
        except Exception:
            pass

    # ---------------------------------------------------------- 失败路径
    lines.append("\n[失败路径]")
    empty = hookfinder.search(os.getpid(), [], seconds=1.0)
    check("没有候选缓冲区 → no-buffer", empty.get("reason") == "no-buffer",
          str(empty.get("reason")))
    bogus = hookfinder.search(999999, [{"address": 0x1000, "encoding": "utf-16"}],
                              seconds=1.0)
    check("打不开的进程 → 明确报错",
          bogus.get("reason") in ("no-access", "attach-failed"),
          str(bogus.get("reason")))
    try:
        hookfinder.locate_buffers(999999, "テスト")
        check("读不了内存时抛 HookFinderError", False, "没抛")
    except hookfinder.HookFinderError as exc:
        check("读不了内存时抛 HookFinderError", exc.reason == "no-access", exc.reason)

    lines.append("")
    lines.append(f"结论：{'全部通过' if not failed else f'{failed} 项失败'}")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告：{REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
