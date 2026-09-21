"""补全窗口的两条止损（2026-09-21 深夜）：别把缓冲垃圾挂到句首，也别丢掉本句的字。"""
from __future__ import annotations

from aurora.platform import memmatch


def test_stray_kanji_prefix_is_dropped() -> None:
    # 实测：`耀一流のレストランに…`（真句是 `一流のレストランに…`）
    text = "耀一流のレストランに行くには少々不安かもしれないが。"
    got = memmatch.trim_sentence(text, (1, 5), probe="一流のレストランに行くには少々不安かもし")
    assert got.startswith("一流のレストランに"), got


def test_leading_bracket_keeps_quote_and_drops_garbage() -> None:
    # 实测：`䐀耀「理由はいくつかあるが……」`
    text = "䐀耀「理由はいくつかあるが……」次"
    got = memmatch.trim_sentence(text, (2, 4), probe="「理由はいくつかあるが……」")
    assert got.startswith("「理由は"), got


def test_kana_prefix_belongs_to_the_sentence() -> None:
    # 实测反例：残片 `つの物思耽で` ← 真句 `いつのまにか物思いに耽っていた…`
    # 那个「い」是本句的字，不能当成垃圾丢掉
    text = "いつのまにか物思いに耽っていたようで。"
    got = memmatch.trim_sentence(text, (1, 4), probe="つの物思耽で")
    assert got.startswith("いつのまにか"), got
