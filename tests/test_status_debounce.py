"""引擎状态推送必须去抖（2026-09-21 卡死事故的回归网）。

现场：文本密的时候一秒 19 行，每行都 `_push_status()` → `evaluate_js`（阻塞、落在
GUI 线程）→ 桥接队列越堆越长，用户点「发送 / 停止翻译」都没反应。
现在最多 4 次/秒，并且被节流掉的那一批一定会补一次尾包；启停等生命周期变化
用 `force=True` 立刻推。
"""
from __future__ import annotations

import time

from aurora.infra import vntext


def make_engine(seen: list) -> vntext.VnTextEngine:
    return vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                               on_line=lambda row: None,
                               on_status=seen.append)


def test_rapid_status_pushes_are_coalesced() -> None:
    seen: list = []
    engine = make_engine(seen)
    start = time.perf_counter()
    for _ in range(20):
        engine._push_status()
    cost = time.perf_counter() - start
    assert cost < 1.0, f"20 次推送自身就花了 {cost:.2f}s"
    assert len(seen) <= 2, f"20 次推送没有合并（推了 {len(seen)} 次）"


def test_trailing_push_arrives() -> None:
    seen: list = []
    engine = make_engine(seen)
    engine._push_status()
    for _ in range(10):
        engine._push_status()
    deadline = time.time() + 2.0
    while time.time() < deadline and len(seen) < 2:
        time.sleep(0.05)
    assert len(seen) >= 2, "被节流的那一批没有补尾包 —— 面板会停在旧状态"


def test_forced_push_is_immediate() -> None:
    seen: list = []
    engine = make_engine(seen)
    engine._push_status()
    before = len(seen)
    engine._push_status(force=True)
    assert len(seen) == before + 1, "force=True 被节流吞掉了（启停状态会迟到）"
