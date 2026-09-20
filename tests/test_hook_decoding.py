"""采样器解码：UTF-8 / UTF-16 双向择优（真机样本驱动）。

来源：2026-09-20 アマカノ３ 找钩子会话 —— 该引擎文本是 UTF-8，旧实现按 UTF-16 读，
候选文本全是「罕见汉字+零散片假名」的乱码（圠荈レ譈䣲骍Ｘ），导致候选全废。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gl.hookfinder import choose_decoding  # noqa: E402

REAL = "義大「周りに人がいるけど」"


def test_prefers_utf8_for_this_engine() -> None:
    text, enc = choose_decoding(REAL.encode("utf-8"))
    assert (text, enc) == (REAL, "utf-8")


def test_still_reads_utf16_text() -> None:
    text, enc = choose_decoding(REAL.encode("utf-16-le"))
    assert text == REAL and enc == "utf-16"


def test_mojibake_loses_to_real_text() -> None:
    """把 UTF-8 字节硬当 UTF-16 读出来的乱码，不能比正确解码更「像台词」。"""
    garbled = REAL.encode("utf-8").decode("utf-16-le", "ignore")
    from aurora.domain.text_rules import hook_candidate_score
    assert hook_candidate_score(garbled) < hook_candidate_score(REAL)
