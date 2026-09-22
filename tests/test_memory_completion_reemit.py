"""缺字补全的「补完版补发」（2026-09-22 遗留项一）。

现场（少女之剑 / WillPlus）：GDI 钩子按字形抓字，字体缓存里没有的字会丢，只能拿
缺字版去**只读扫游戏内存**配真句。全量扫描实测 44~68 秒，所以取词链路最多等 2.5 秒
就先放行缺字版（不然一句要等半分钟）。

遗留问题：扫出来的补完版只进了缓存 —— 这一句永远停在缺字版上，要等剧情里同一句
再次出现才看得到完整译文。

现在：后台扫出结果时作为「同一句的新版本」补发（发射带 `revise_of` = 那条缺字版的
发射序号），翻译侧按序号原位替换，不新增一条。
"""
from __future__ import annotations

import threading
import time

from aurora.infra import vntext
from aurora.platform import memmatch

FRAGMENT = "家近離心倒"
FIXED = "家が近所で、年が離れていることもあって、姉さんは真面目を絵に描いたような人で。"


def make_engine(seen: list) -> vntext.VnTextEngine:
    engine = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                 on_line=seen.append)
    engine._pid = 4321
    engine._mode = "hook"      # 会话在跑（_arm_completion 的闸）
    engine._engine = "WillPlus"
    engine._seen["gdi"] = {"name": "TextOutW", "code": "", "count": 1, "sample": "",
                           "dialogue": 1, "last_seen": 0.0}
    return engine


def promote(engine: vntext.VnTextEngine, clean: str) -> None:
    engine._promote({"key": "gdi", "clean": clean,
                     "norm": vntext.normalize_for_dedupe(clean),
                     "text": clean, "probe": clean})


def test_late_completion_is_reemitted_as_a_new_version(monkeypatch) -> None:
    seen: list = []
    engine = make_engine(seen)

    def slow_complete(pid, fragment, *, wait=2.5, on_done=None):
        if on_done:
            on_done(FIXED)         # 后台扫完：回调固定早于等待者返回
        return ""                  # 等待已超时 → 先放行缺字版

    monkeypatch.setattr(memmatch, "complete_async", slow_complete)
    promote(engine, FRAGMENT)
    assert [row["text"] for row in seen] == [FRAGMENT], \
        "超时那次必须先放行缺字版（不能退回 44~68 秒的同步等待）"

    engine._resolve_completions()
    assert [row["text"] for row in seen] == [FRAGMENT, FIXED], "补完版没有补发"
    assert seen[1]["revise_of"] == seen[0]["id"], "补发必须认领那条缺字版"
    assert engine.status()["revised"] == 1
    assert engine.status()["lines"] == 1, "补发是同一句的新版本，不该算成新台词"


def test_sync_completion_does_not_reemit(monkeypatch) -> None:
    seen: list = []
    engine = make_engine(seen)

    def fast_complete(pid, fragment, *, wait=2.5, on_done=None):
        if on_done:
            on_done(FIXED)         # 真实实现里回调也早于同步返回
        return FIXED               # 没超时：这一句直接按补完版发射

    monkeypatch.setattr(memmatch, "complete_async", fast_complete)
    promote(engine, FRAGMENT)
    assert [row["text"] for row in seen] == [FIXED]
    engine._resolve_completions()
    assert [row["text"] for row in seen] == [FIXED], \
        "同步拿到补完版的那次不该再补发（缺字版压根没发射过）"
    assert engine.status()["revised"] == 0


def test_completion_arriving_from_the_scan_thread_is_attached(monkeypatch) -> None:
    """按 memmatch 的真实时序演一遍：回调在**后台线程**、早于等待者返回。"""
    seen: list = []
    engine = make_engine(seen)

    def threaded_complete(pid, fragment, *, wait=2.5, on_done=None):
        finished = threading.Event()

        def scan() -> None:
            time.sleep(0.05)
            if on_done:
                on_done(FIXED)
            finished.set()

        threading.Thread(target=scan, daemon=True, name="fake-memmatch").start()
        finished.wait(0.5)
        return ""                  # 等待超时 → 缺字版先发射

    monkeypatch.setattr(memmatch, "complete_async", threaded_complete)
    promote(engine, FRAGMENT)
    engine._resolve_completions()
    assert [row["text"] for row in seen] == [FRAGMENT, FIXED]
    assert seen[1]["revise_of"] == seen[0]["id"]


def test_fix_for_a_line_that_was_never_emitted_is_dropped() -> None:
    seen: list = []
    engine = make_engine(seen)
    engine._attach_completion(engine._arm_completion(FRAGMENT), FIXED)
    engine._resolve_completions()
    assert seen == [], "没认领到缺字版的补完版不能当新台词发出去"


def test_fix_does_not_claim_an_older_emission() -> None:
    seen: list = []
    engine = make_engine(seen)
    promote(engine, FRAGMENT)                     # 先发射（上一句）
    engine._attach_completion(engine._arm_completion(FRAGMENT), FIXED)   # 补完版这时才到
    engine._resolve_completions()
    assert [row["text"] for row in seen] == [FRAGMENT], \
        "只认领「认领时刻之后」发射的缺字版，别去改上一句"


def test_expired_fix_is_dropped(monkeypatch) -> None:
    seen: list = []
    engine = make_engine(seen)
    engine._attach_completion(engine._arm_completion(FRAGMENT), FIXED)
    claim = engine._pending_fixes[0]
    claim["at"] -= engine.COMPLETION_CLAIM_TTL + 10
    monkeypatch.setattr(memmatch, "complete_async",
                        lambda pid, fragment, *, wait=2.5, on_done=None: "")
    promote(engine, FRAGMENT)
    engine._resolve_completions()
    assert [row["text"] for row in seen] == [FRAGMENT]
    assert not any(row is claim for row in engine._pending_fixes), \
        "过期的补发请求要丢掉，不能越积越多"


def test_stopped_session_does_not_queue_fixes() -> None:
    seen: list = []
    engine = make_engine(seen)
    engine._stop.set()
    engine._attach_completion(engine._arm_completion(FRAGMENT), FIXED)
    assert engine._pending_fixes == []
