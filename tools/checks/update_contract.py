r"""刷新桥接契约快照（`docs/architecture/contracts/bridge-contract.json`）。

什么时候用：**有意**新增/删除桥接方法、事件主题或悬浮窗动作之后。
用法：
    python tools\checks\update_contract.py            # 只看差异，不写文件
    python tools\checks\update_contract.py --write    # 写入快照

注意：改名/删方法属于破坏性变更（ADR-0006），必须有 ADR 并同步前端；
这个脚本只负责把「当前事实」写进快照，不做判断。
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import (ROOT, class_methods, emitted_topics, frontend_calls,  # noqa: E402
                    function_signature, load_json)

CONTRACT = ROOT / "docs" / "architecture" / "contracts" / "bridge-contract.json"
API = "gl/api.py"
OVERLAY = "gl/overlay.py"
APP_JS = "gl/web/app.js"


def classify(name: str) -> str:
    """按前缀粗分类（仅供阅读，不是契约）。"""
    if name.startswith("_"):
        return "internal"
    for prefix, kind in (("get_", "query"), ("list_", "query"), ("read", "query"),
                         ("bootstrap", "query"), ("scan_", "command"), ("test_", "command"),
                         ("pick_", "dialog"), ("open_", "dialog"), ("refresh_", "command")):
        if name.startswith(prefix):
            return kind
    return "command"


def build() -> dict:
    current = load_json("docs/architecture/contracts/bridge-contract.json")
    calls = frontend_calls(APP_JS)

    main_methods = []
    live_main = class_methods(API, "Api")
    for name in sorted(live_main):
        if name.startswith("__"):
            continue
        sig = function_signature(live_main[name])
        main_methods.append({
            "name": name,
            "params": sig["params"],
            "returns": sig["returns"],
            "kind": classify(name),
            "internal": name.startswith("_"),
            "called_by_frontend": name in calls,
        })

    overlay_methods = []
    for name, fn in sorted(class_methods(OVERLAY, "OverlayBridge").items()):
        if name.startswith("__"):
            continue
        sig = function_signature(fn)
        overlay_methods.append({
            "name": name,
            "params": sig["params"],
            "returns": sig["returns"],
            "called_by_frontend": name in {"ready", "save_bounds", "begin_resize", "action"},
        })

    sources = [API, "gl/downloads.py", "gl/overlay.py"]
    sources += sorted(p.relative_to(ROOT).as_posix()
                      for p in (ROOT / "aurora" / "ui" / "bridge").glob("*.py"))
    topics = sorted(emitted_topics(*sources))
    payload = dict(current)
    payload["channels"] = {
        "main": {
            "js_api": "gl.api.Api",
            "method_count": len(main_methods),
            "public_method_count": sum(1 for m in main_methods if not m["internal"]),
            "internal_method_count": sum(1 for m in main_methods if m["internal"]),
            "frontend_call_count": len(calls),
            "excluded_members": ["__init__"],
            "methods": main_methods,
        },
        "overlay": {
            "js_api": "gl.overlay.OverlayBridge",
            "method_count": len(overlay_methods),
            "excluded_members": ["__init__"],
            "methods": overlay_methods,
        },
    }
    payload["events"] = topics
    return payload


def main() -> int:
    before = json.loads(CONTRACT.read_text(encoding="utf-8"))
    after = build()

    old_names = {m["name"] for m in before["channels"]["main"]["methods"]}
    new_names = {m["name"] for m in after["channels"]["main"]["methods"]}
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    events_added = sorted(set(after["events"]) - set(before["events"]))
    events_removed = sorted(set(before["events"]) - set(after["events"]))

    print(f"桥接方法：{len(old_names)} → {len(new_names)}")
    print(f"  新增：{added or '无'}")
    print(f"  消失：{removed or '无'}")
    print(f"事件主题：{len(before['events'])} → {len(after['events'])}")
    print(f"  新增：{events_added or '无'}")
    print(f"  消失：{events_removed or '无'}")

    if "--write" in sys.argv:
        CONTRACT.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(f"\n已写入 {CONTRACT.relative_to(ROOT)}")
        return 0

    diff = bool(added or removed or events_added or events_removed)
    print("\n（干跑：加 --write 才会写文件）")
    return 0 if not diff else 1


if __name__ == "__main__":
    sys.exit(main())
