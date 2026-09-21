"""重复台词必须还能再发一次（2026-09-22 白色相簿2 实测）。

现场：`とうとう、降ってきた。` 在剧情里**再次出现**（文学重复），却因为老逻辑
「最近 8 条里出现过就丢」而没有时间窗，被当成重复文本吞掉、再也没有译文。

现在这条抑制带 10 秒窗口：钩子侧的真重复（多线程/重绘重发）都在几秒内到，挡得住；
隔了半分钟再出现的同一句是正文，要照常发射（译文会命中缓存，瞬间返回）。
"""
from __future__ import annotations

from aurora.infra import vntext


def make_engine(seen: list) -> vntext.VnTextEngine:
    engine = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                 on_line=seen.append)
    engine._seen["t"] = {"name": "KiriKiriZ", "code": "", "count": 1, "sample": "",
                         "dialogue": 1, "last_seen": 0.0}
    return engine


def emit(engine: vntext.VnTextEngine, text: str) -> None:
    engine._promote({"key": "t", "clean": text,
                     "norm": vntext.normalize_for_dedupe(text),
                     "text": text, "probe": text})


def age(engine: vntext.VnTextEngine, seconds: float) -> None:
    """把「最近文本」的时间戳往前挪，模拟过了 N 秒。"""
    with engine._lock:
        engine._recent_text = [(t, at - seconds) for t, at in engine._recent_text]
        engine._recent = [(n, at - seconds) for n, at in engine._recent]


def test_repeat_after_a_gap_is_emitted_again() -> None:
    seen: list = []
    engine = make_engine(seen)
    emit(engine, "とうとう、降ってきた。")
    emit(engine, "別の台詞です。")
    age(engine, 32.0)                       # 现场就是隔了 32 秒
    emit(engine, "とうとう、降ってきた。")
    assert [row["text"] for row in seen].count("とうとう、降ってきた。") == 2, \
        "同一句隔了半分钟再出现是正文，不该被去重吞掉"


def test_immediate_duplicate_is_still_merged() -> None:
    seen: list = []
    engine = make_engine(seen)
    emit(engine, "とうとう、降ってきた。")
    emit(engine, "とうとう、降ってきた。")   # 同一瞬间的钩子重发
    assert [row["text"] for row in seen] == ["とうとう、降ってきた。"], \
        "钩子侧的即时重发仍要被挡住"
