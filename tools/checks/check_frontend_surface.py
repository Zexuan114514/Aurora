"""前端测试面守卫（v2）：

- 探针引用的 DOM id 必须在新前端源码里出现（少一个 = e2e 会静默失败）
- `window.__aurora` 的键与 14 个事件主题必须在源码里出现

快照 `docs/architecture/contracts/frontend-surface.json` 由本脚本 `--write` 生成
（从 tools/*.py 里扫 getElementById / querySelector('#id') / real_click('#id')）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from common import ROOT, Result, main

SNAPSHOT = ROOT / "docs" / "architecture" / "contracts" / "frontend-surface.json"
SRC = ROOT / "frontend" / "src"
TOOLS = ROOT / "tools"

_ID_PATTERNS = (
    re.compile(r"getElementById\(\s*['\"]([A-Za-z0-9_\-]+)['\"]"),
    re.compile(r"querySelector\(\s*['\"]#([A-Za-z0-9_\-]+)"),
    re.compile(r"real_click\(\s*['\"]#([A-Za-z0-9_\-]+)"),
)

#: 快照里会出现、但**不该**在前端源码里找的 id：
#:  * 探针自己造出来的节点（前端没有、也不需要提供）；
#:  * 反向断言用的 id（判据要求它「已经不存在」）。
NOT_FRONTEND_IDS = {
    "theme-freeze",     # tools/visual.py 注入的 <style> 的 id
    "addMenu",          # P8.6 删掉的二选一菜单：e2e 反向断言它不再存在
}
_AURORA_KEYS = ("ring", "layout", "emit", "dispatch")
_AURORA_ERRORS = "__auroraErrors"


def scan_tools() -> tuple[list[str], list[str]]:
    ids: set[str] = set()
    for path in TOOLS.rglob("*.py"):
        if path.name == Path(__file__).name:
            continue          # 别扫自己：文档字符串里就写着 '#id' 这两个例子
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _ID_PATTERNS:
            ids.update(pattern.findall(text))
    events: set[str] = set()
    contract = ROOT / "docs" / "architecture" / "contracts" / "bridge-contract.json"
    if contract.is_file():
        payload = json.loads(contract.read_text(encoding="utf-8"))
        events.update(payload.get("events") or [])
    return sorted(ids), sorted(events)


def source_text() -> str:
    chunks: list[str] = []
    for path in SRC.rglob("*"):
        if path.is_file() and path.suffix in (".vue", ".ts", ".css"):
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def write_snapshot() -> int:
    ids, events = scan_tools()
    payload = {
        "schema": "aurora.frontend-surface/1",
        "note": "探针引用的 DOM id + window.__aurora 键 + 事件主题；check_frontend_surface.py 校验",
        "dom_ids": ids,
        "aurora_keys": list(_AURORA_KEYS),
        "aurora_errors": _AURORA_ERRORS,
        "event_topics": events,
    }
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {SNAPSHOT.relative_to(ROOT)}：{len(ids)} 个 id、{len(events)} 个事件主题")
    return 0


def check() -> Result:
    result = Result("前端测试面（id / __aurora / 事件主题）")
    if not SNAPSHOT.is_file():
        result.fail("缺少快照 docs/architecture/contracts/frontend-surface.json"
                    "（跑 python tools\\checks\\check_frontend_surface.py --write）")
        return result
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    text = source_text()
    if not text.strip():
        result.fail("frontend/src 下没有可扫描的源码")
        return result

    missing_ids = [name for name in payload.get("dom_ids", [])
                   if name not in NOT_FRONTEND_IDS
                   if f'id="{name}"' not in text and f'getElementById("{name}")' not in text
                   and f"getElementById('{name}')" not in text]
    if missing_ids:
        result.fail(f"{len(missing_ids)} 个探针用的 DOM id 在新前端里找不到："
                    + ", ".join(missing_ids[:10]) + ("…" if len(missing_ids) > 10 else ""))

    missing_keys = [key for key in payload.get("aurora_keys", [])
                    if f"{key}:" not in text and f"{key}(" not in text]
    if missing_keys:
        result.fail("window.__aurora 缺键：" + ", ".join(missing_keys))
    if payload.get("aurora_errors") and payload["aurora_errors"] not in text:
        result.fail("源码里找不到 __auroraErrors（错误收集面）")

    missing_events = [topic for topic in payload.get("event_topics", [])
                      if f'"{topic}"' not in text and f"'{topic}'" not in text]
    if missing_events:
        result.fail(f"{len(missing_events)} 个事件主题没在源码里出现："
                    + ", ".join(missing_events))

    if not result.failures:
        result.note(f"{len(payload.get('dom_ids', []))} 个 id + "
                    f"{len(payload.get('aurora_keys', []))} 个 __aurora 键 + "
                    f"{len(payload.get('event_topics', []))} 个事件主题齐备")
    return result


if __name__ == "__main__":
    if "--write" in sys.argv:
        sys.exit(write_snapshot())
    sys.exit(main(check))
