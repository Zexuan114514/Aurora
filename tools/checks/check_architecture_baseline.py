"""基线守卫：模块与线程清单只能按登记的方式变化（P1-P3 迁移期靠它兜底）。"""
from __future__ import annotations

import json
import re
import sys

from common import ROOT, Result, load_json, main

BASELINE = "tools/checks/baseline.json"


def line_count(path) -> int:      # noqa: ANN001
    return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())


def current_threads() -> dict[str, str]:
    found: dict[str, str] = {}
    roots = sorted((ROOT / "gl").rglob("*.py")) + [ROOT / "main.py"]
    if (ROOT / "aurora").exists():
        roots += sorted((ROOT / "aurora").rglob("*.py"))
    for path in roots:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            # 前面必须是边界：避免把 save_filename="aurora-library.json" 这类当成线程名
            match = (re.search(r'(?<![A-Za-z_])name=(f?)"(aurora-[^"]+)"', line)
                     or re.search(r'thread_name=(f?)"(aurora-[^"]+)"', line))
            if match:
                found[match.group(2)] = path.relative_to(ROOT).as_posix()
    return found


def check() -> Result:
    result = Result("架构基线（模块 / 线程 / 体积）")
    baseline = load_json(BASELINE)
    superseded = baseline.get("superseded_by") or {}
    tolerance = float((baseline.get("tolerances") or {}).get("module_line_drift_pct") or 25)

    missing, drifted, moved = [], [], []
    for entry in baseline["modules"]:
        path = ROOT / entry["path"]
        if not path.exists():
            replacement = superseded.get(entry["path"])
            if replacement:
                moved.append(f"{entry['path']} → {replacement}")
                continue
            missing.append(entry["path"])
            continue
        now = line_count(path)
        base = int(entry["lines"]) or 1
        drift = abs(now - base) / base * 100
        if drift > tolerance:
            drifted.append(f"{entry['path']} {base} → {now} 行（{drift:.0f}%）")
    if missing:
        result.fail(f"基线里的模块消失了（搬家请写进 baseline.superseded_by）：{', '.join(missing)}")
    for item in drifted:
        result.warn(f"行数漂移超过 {tolerance:.0f}%：{item}")
    for item in moved:
        result.note(f"已登记的搬家：{item}")

    baselined = {entry["path"] for entry in baseline["modules"]}
    watched = list((ROOT / "gl").rglob("*.py")) + list((ROOT / "gl/web").glob("*.*")) + [ROOT / "main.py"]
    if (ROOT / "aurora").exists():
        watched += list((ROOT / "aurora").rglob("*.py"))
    on_disk = {p.relative_to(ROOT).as_posix() for p in watched
               if p.is_file() and "__pycache__" not in p.parts}
    fresh = sorted(on_disk - baselined)
    if fresh:
        result.warn(f"基线之后新增的文件（确认后补登记）：{', '.join(fresh)}")

    live_threads = current_threads()
    gone_threads = sorted({entry["name"] for entry in baseline["threads"]
                           if entry["name"] not in live_threads and entry["name"] not in superseded})
    if gone_threads:
        result.warn(f"基线里的线程名消失了（P3 收口时更新 baseline）：{', '.join(gone_threads)}")
    new_threads = sorted(set(live_threads) - {entry["name"] for entry in baseline["threads"]})
    if new_threads:
        result.warn(f"新增线程未登记：{', '.join(new_threads)}")
    result.note(f"具名线程 {len(live_threads)} 个（去重后），基线清单 {len(baseline['threads'])} 行")

    baseline_exe = baseline["artifacts"]["aurora_exe_bytes"]
    exe = ROOT / "Aurora.exe"
    if exe.exists():
        now_mb = exe.stat().st_size / 1048576
        base_mb = baseline_exe / 1048576
        result.note(f"Aurora.exe {now_mb:.1f} MB（基线 {base_mb:.1f} MB）")
    data = baseline["data"]
    live_library = ROOT / "data" / "library.json"
    if live_library.exists():
        live = json.loads(live_library.read_text(encoding="utf-8"))
        result.note(f"实时库 {len(live.get('games') or [])} 游戏 / "
                    f"{len(live.get('settings') or {})} 设置项"
                    f"（基线 {data['games']} 游戏 / {data['settings_keys']} 设置项；"
                    f"用户数据自然增长，不判失败）")
    result.note(f"桥接基线：{baseline['bridge']['public_methods']} 公开方法 / "
                f"{baseline['bridge']['frontend_call_points']} 前端调用点 / "
                f"{baseline['bridge']['event_topics']} 事件主题")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
