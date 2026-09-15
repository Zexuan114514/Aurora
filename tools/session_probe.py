"""会话自检：进程树判定、时长结算、启动次数、LE 启动参数透传。

覆盖三种现实场景：
  1. 直接启动 exe            -> 按「镜像路径 = 游戏 exe」认出本体
  2. 引导 bat 拉起子进程后自己退出 -> 仍判运行中（老实现会误判成已结束）
  3. 假 LEProc 转区启动       -> 传给 LE 的 argv 完整、顺序不变
结果写入 tools/session-report.txt。
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox"
WORK = SANDBOX / "session-fake"
TEST_DATA = SANDBOX / "session-data"
REPORT = Path(__file__).resolve().parent / "session-report.txt"
GUID = "{33333333-3333-3333-3333-333333333333}"
PING = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "ping.exe"

os.environ["AURORA_DATA"] = str(TEST_DATA)

from gl import locale, process as gprocess, proctree  # noqa: E402
from gl.api import Api  # noqa: E402
from gl.process import ProcessManager  # noqa: E402

failed = 0


def wait_for(predicate, timeout: float, interval: float = 0.4) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def build_fixtures() -> dict:
    WORK.mkdir(parents=True, exist_ok=True)
    selfgame = WORK / "selfgame.exe"
    if not selfgame.exists():
        shutil.copy2(PING, selfgame)

    # 引导 bat：拉起 ping 后自己立刻退出（模拟「启动器 exe / LEProc 先退」）
    boot = WORK / "boot.bat"
    boot.write_text(f'@echo off\r\nstart "" /b "{PING}" -n 40 127.0.0.1\r\n',
                    encoding="gbk")
    # 会自己结束的游戏：跑 3 秒左右
    quick = WORK / "quick.bat"
    quick.write_text(f'@echo off\r\n"{PING}" -n 4 127.0.0.1 > nul\r\n', encoding="gbk")
    return {"self": selfgame, "boot": boot, "quick": quick}


def kill_leftovers(pids) -> None:
    for pid in sorted({int(p) for p in pids if p}):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, creationflags=0x08000000, timeout=10)
        except Exception:
            pass


def main() -> int:
    out = io.StringIO()

    def write(line: str = "") -> None:
        out.write(line + "\n")

    def check(label: str, ok: bool, detail="") -> bool:
        global failed
        if not ok:
            failed += 1
        write(f"  {'OK ' if ok else 'BAD'} {label}" + (f"  {detail}" if detail else ""))
        return ok

    # 每次从干净的数据目录开始，避免上一次的 play_count / sessions 干扰断言
    shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)

    files = build_fixtures()
    pm = ProcessManager()
    events: list[tuple] = []
    pm.set_callbacks(
        on_found=lambda gid, pid: events.append(("found", gid, pid)),
        on_exit=lambda gid, sec: events.append(("exit", gid, sec)),
    )
    leftovers: list[int] = []

    write("Aurora 会话 / 进程树自检")
    write("=" * 52)

    # ---------------------------------------------------------------- 1
    write("\n[1] 直接启动 exe：按镜像路径认本体")
    res = pm.start({"id": "direct", "exe": str(files["self"]), "workdir": str(WORK),
                    "launch_args": "-n 25 127.0.0.1"})
    check("启动返回 ok", bool(res.get("ok")), str(res))
    found = wait_for(lambda: any(e[0] == "found" and e[1] == "direct" for e in events), 12)
    pid = pm.game_pid("direct")
    leftovers.append(pid)
    matched = (pm._running.get("direct") or {}).get("matched_by")
    check("20s 内认出游戏本体", found and pid != 0, f"pid={pid} matched_by={matched}")
    check("按路径匹配（不是子树）", matched == "path", str(matched))
    image = gprocess.process_image(pid)
    check("认出的 pid 镜像路径就是游戏 exe",
          Path(image).name.lower() == files["self"].name.lower(), image or "(读不到镜像路径)")
    stopped = pm.stop("direct")
    tail = [e for e in events if e[0] == "exit" and e[1] == "direct"]
    check("手动结束后结算时长", bool(tail) and float(tail[-1][2]) > 0,
          f"seconds={tail[-1][2]:.1f}" if tail else "没有 exit 回调")
    check("结束后不再算运行中", not pm.is_running("direct"))
    write(f"       killed={stopped.get('killed')}")

    # ---------------------------------------------------------------- 2
    write("\n[2] 引导 bat 自己退出：仍判运行中（老实现会误判结束）")
    res = pm.start({"id": "boot", "exe": str(files["boot"]), "workdir": str(WORK)})
    check("启动返回 ok", bool(res.get("ok")), str(res))
    wait_for(lambda: any(e[0] == "found" and e[1] == "boot" for e in events), 12)
    time.sleep(4)   # 等引导 cmd.exe 自己退出之后再看
    boot_pid = pm.game_pid("boot")
    leftovers.append(boot_pid)
    tree_matched = (pm._running.get("boot") or {}).get("matched_by")
    check("引导进程退出后仍判运行中", pm.is_running("boot"),
          f"pid={boot_pid} matched_by={tree_matched}")
    check("按子树匹配到了真正的游戏进程", tree_matched == "tree" and boot_pid != 0,
          str(tree_matched))
    stopped = pm.stop("boot")
    tail = [e for e in events if e[0] == "exit" and e[1] == "boot"]
    check("手动结束也结算时长", bool(tail) and float(tail[-1][2]) > 0,
          f"seconds={tail[-1][2]:.1f}" if tail else "没有 exit 回调")
    leftovers += list(stopped.get("killed") or [])
    time.sleep(1.0)
    check("子进程确实被结束", not proctree.is_alive(boot_pid), f"pid={boot_pid}")

    # ---------------------------------------------------------------- 3
    write("\n[3] 游戏自然退出：play_count / sessions / 时长入账")
    api = Api()
    try:
        gid = "session-probe"
        api._library.add({"id": gid, "name": "probe", "exe": str(files["quick"]),
                          "workdir": str(WORK)})
        launched = api.launch(gid)
        check("api.launch 返回 ok", bool(launched.get("ok")), str(launched))
        row = api._library.get(gid)
        check("启动次数 +1", int(row.get("play_count") or 0) == 1, str(row.get("play_count")))
        ended = wait_for(lambda: not api._pm.is_running(gid), 45, 1.0)
        row = api._library.get(gid)
        sessions = list(row.get("sessions") or [])
        check("运行结束后自动结算（不用手动点结束）", ended,
              f"running={api._pm.is_running(gid)}")
        check("会话写进 sessions", len(sessions) == 1
              and int(sessions[-1]["seconds"]) >= 2,
              str(sessions[-1] if sessions else {}))
        check("累计时长入账", int(row.get("play_time") or 0) >= 2, str(row.get("play_time")))
        check("会话标记被清掉",
              int(row.get("play_pid") or 0) == 0 and int(row.get("play_launcher_pid") or 0) == 0
              and int(row.get("play_started_at") or 0) == 0,
              f"pid={row.get('play_pid')} launcher={row.get('play_launcher_pid')}")

        # ------------------------------------------------------------ 4
        write("\n[4] 转区启动：argv 原样交给 LE")
        argv_file = WORK / "le-argv.txt"
        if argv_file.exists():
            argv_file.unlink()
        writer = (
            "import sys, time, pathlib\n"
            "pathlib.Path(sys.argv[1]).write_text('|'.join(sys.argv[2:]), encoding='utf-8')\n"
            "time.sleep(20)\n"
        )
        le_argv = locale.build_command("LEProc.exe", str(files["self"]), ["-n", "5"],
                                       guid=GUID)[1:]
        launcher = [sys.executable, "-c", writer, str(argv_file)] + le_argv
        res = pm.start({"id": "le", "exe": str(files["self"]), "workdir": str(WORK)},
                       launcher=launcher)
        check("带 launcher 启动成功", bool(res.get("ok")), str(res))
        got = wait_for(lambda: argv_file.exists(), 10)
        text = argv_file.read_text(encoding="utf-8") if got else ""
        want = "|".join(["-runas", GUID, str(files["self"]), "-n", "5"])
        check("LE 收到 -runas <GUID> <exe> <参数>", text == want, text or "(没写出 argv)")
        pm.stop("le")
        leftovers.append(int(res.get("pid") or 0))
    finally:
        api._downloads.stop()

    kill_leftovers(leftovers)
    write("\n结论: " + ("全部通过" if not failed else f"{failed} 项失败"))
    text = out.getvalue()
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
