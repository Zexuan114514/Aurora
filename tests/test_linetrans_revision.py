"""补完版的译文原位替换（缺字补全补发的下游一半）。

上游见 `tests/test_memory_completion_reemit.py`：引擎把补完版作为「同一句的新版本」
补发（`revise_of` = 缺字版的发射序号）。翻译这边必须：

* 原位替换那条历史（面板上不能出现「残句 + 完整句」两条）；
* 缺字版本的译文要是**后**到（LLM 慢、补发先出），直接丢掉，不能把面板/悬浮窗顶回去；
* 要补发的那句已经是旧台词时（玩家早就翻页了）只更新面板，别去顶悬浮窗。
"""
from __future__ import annotations

import time
import types

from aurora.app.services.vntext import VnTextService
from aurora.infra.linetrans import LineTranslator


def make_translator(events: list) -> LineTranslator:
    return LineTranslator(settings_getter=lambda: {"vntext_max_chars": 1200},
                          on_event=lambda kind, payload: events.append((kind, payload)))


def job(text: str, *, line_id: int = 0, revise_of: int = 0, source: str = "hook") -> dict:
    return {"text": text, "game_id": "game-1", "source": source,
            "line_id": line_id, "revise_of": revise_of, "at": time.time()}


def test_revision_replaces_the_fragment_entry_in_place() -> None:
    events: list = []
    translator = make_translator(events)
    translator._finish(job("家近離心倒", line_id=7), "残句译文", provider="cache")
    translator._finish(job("家が近所で、年が離れていることもあって。", line_id=8, revise_of=7),
                       "完整译文", provider="cache")
    history = translator.history(10)
    assert len(history) == 1, f"补完版不该新增一条：{history}"
    assert history[0]["text"] == "家が近所で、年が離れていることもあって。"
    assert history[0]["translation"] == "完整译文"
    assert history[0]["id"] == 7, "补完版占的是缺字版那条的位置（id 不变）"
    assert history[0].get("revised") is True


def test_late_fragment_translation_is_dropped() -> None:
    events: list = []
    translator = make_translator(events)
    # 补完版先出（缺字版那次请求还在飞）
    translator._finish(job("完整版台词。", line_id=8, revise_of=7), "完整译文",
                       provider="llm")
    events.clear()
    translator._finish(job("家近離心倒", line_id=7), "残句译文", provider="llm")
    history = translator.history(10)
    assert [row["text"] for row in history] == ["完整版台词。"], \
        "缺字版的译文后到就直接丢，别把完整译文顶掉"
    assert [kind for kind, _payload in events] == [], "被丢掉的译文不该再发事件"


def test_late_fragment_job_is_not_translated() -> None:
    events: list = []
    translator = make_translator(events)
    translator._finish(job("完整版台词。", line_id=8, revise_of=7), "完整译文",
                       provider="cache")
    events.clear()
    translator._run(job("家近離心倒", line_id=7))       # 排队里剩下的缺字版
    assert [row["text"] for row in translator.history(10)] == ["完整版台词。"]
    assert events == [], "缺字版已经被替换过，连翻译请求都不该再发"


def test_revision_of_an_old_line_is_silent() -> None:
    events: list = []
    translator = make_translator(events)
    translator._finish(job("残片A", line_id=1), "A 译文", provider="cache")
    translator._finish(job("后面那句。", line_id=2), "B 译文", provider="cache")
    with translator._lock:
        assert translator._revision_is_stale(1) is True, "已经是旧台词 → 别顶悬浮窗"
        assert translator._revision_is_stale(2) is False, "还是当前这句 → 悬浮窗照常更新"


def test_silent_flag_reaches_the_event() -> None:
    events: list = []
    translator = make_translator(events)
    translator._fire("done", {"text": "旧台词"}, silent=True)
    assert events == [("done", {"text": "旧台词", "silent": True})]


def test_service_forwards_line_id_and_revise_of() -> None:
    calls: list = []
    stub = types.SimpleNamespace(submit=lambda text, **kw: calls.append((text, kw)))
    service = types.SimpleNamespace(_translator=stub)
    VnTextService._on_vntext_line(service, {"text": "完整版台词。", "source": "hook",
                                            "id": 8, "revise_of": 7})
    assert calls == [("完整版台词。", {"game_id": "", "source": "hook",
                                       "line_id": 8, "revise_of": 7})]
