"""契约守卫：桥接方法、事件主题必须与快照完全一致（ADR-0006）。"""
from __future__ import annotations

import sys

from common import (ROOT, Result, class_methods, emitted_topics, frontend_calls,
                    function_signature, load_json, main)

CONTRACT = "docs/architecture/contracts/bridge-contract.json"
API = "gl/api.py"
OVERLAY = "gl/overlay.py"
APP_JS = "gl/web/app.js"


def check() -> Result:
    result = Result("契约快照（桥接 + 事件）")
    contract = load_json(CONTRACT)
    channels = contract["channels"]

    live_main = class_methods(API, "Api")
    snap_main = {m["name"]: m for m in channels["main"]["methods"]}
    excluded = set(channels["main"].get("excluded_members") or [])
    live_public = {name for name in live_main if not name.startswith("_")}
    live_all = {name for name in live_main if name not in excluded}

    missing = sorted(live_all - set(snap_main))
    extra = sorted(set(snap_main) - live_all)
    if missing:
        result.fail(f"快照缺少后端方法（新增方法要同步快照）：{', '.join(missing)}")
    if extra:
        result.fail(f"快照记录了不存在的方法（改名/删除必须走 ADR）：{', '.join(extra)}")

    for name, meta in snap_main.items():
        if name not in live_main:
            continue
        live_sig = function_signature(live_main[name])
        snap_params = [(p["name"], p["type"]) for p in meta["params"]]
        live_params = [(p["name"], p["type"]) for p in live_sig["params"]]
        if snap_params != live_params:
            result.fail(f"{name} 参数与快照不一致：快照 {snap_params} / 代码 {live_params}")
        if meta["returns"] != live_sig["returns"]:
            result.fail(f"{name} 返回标注与快照不一致：{meta['returns']} -> {live_sig['returns']}")

    internal_snap = {m["name"] for m in channels["main"]["methods"] if m["internal"]}
    internal_live = {name for name in live_main if name.startswith("_") and name not in excluded}
    if internal_snap != internal_live:
        result.note(f"内部方法集合变化（不阻断）：新增 {sorted(internal_live - internal_snap)}，"
                    f"消失 {sorted(internal_snap - internal_live)}")

    calls = frontend_calls(APP_JS)
    flagged = {m["name"] for m in channels["main"]["methods"] if m.get("called_by_frontend")}
    if calls != flagged:
        result.fail(f"前端调用点与快照不一致：新增调用 {sorted(calls - flagged)}，"
                    f"不再调用 {sorted(flagged - calls)}")
    unknown = sorted(calls - live_all)
    if unknown:
        result.fail(f"前端调用了后端不存在的方法：{', '.join(unknown)}")
    result.note(f"前端调用点 {len(calls)} 个，全部有后端实现")

    live_overlay = class_methods(OVERLAY, "OverlayBridge")
    snap_overlay = {m["name"] for m in channels["overlay"]["methods"]}
    excluded_overlay = set(channels["overlay"].get("excluded_members") or [])
    if snap_overlay != set(live_overlay) - excluded_overlay:
        result.fail(f"悬浮窗桥接与快照不一致：快照 {sorted(snap_overlay)} / "
                    f"代码 {sorted(set(live_overlay) - excluded_overlay)}")

    live_topics = emitted_topics(API, "gl/downloads.py", "gl/overlay.py")
    snap_topics = set(contract["events"])
    if live_topics - snap_topics:
        result.fail(f"代码里 emit 了新主题但快照没有：{sorted(live_topics - snap_topics)}")
    if snap_topics - live_topics:
        result.fail(f"快照里的主题已不在代码里 emit：{sorted(snap_topics - live_topics)}")
    result.note(f"事件主题 {len(snap_topics)} 个，与代码 emit 集合一致")

    actions = set(contract["overlay_actions"])
    overlay_src = (ROOT / OVERLAY).read_text(encoding="utf-8") + (ROOT / API).read_text(encoding="utf-8")
    for action in sorted(actions):
        if f'"{action}"' not in overlay_src:
            result.fail(f"悬浮窗动作 {action} 在代码里找不到实现")
    result.note(f"悬浮窗动作 {len(actions)} 个：{', '.join(sorted(actions))}")

    result.note(f"公开桥接方法 {len(live_public)} 个（快照 {channels['main']['public_method_count']}）")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
