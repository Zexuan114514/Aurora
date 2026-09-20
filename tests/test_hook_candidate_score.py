"""钩子候选打分：用真机日志里的样本锁住「像不像台词」的判定。

样本来源：2026-09-20 アマカノ３ 找钩子会话（data/logs/aurora.log）——
左边是真台词（用户钩子吐出），右边是候选钩子读到的乱码。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.domain.text_rules import hook_candidate_score  # noqa: E402

REAL_LINES = [
    "義大「周りに人がいるけど」",
    "詩夢「それが？」",
    "うん、これはするしかない。",
    "覚悟を決めて、詩夢にキスをする。",
    "子供扱いじゃないとしたら……。",
]
NOISE_LINES = [
    "@ 8@\\x01@ 8@\\x01@ 8@\\x01@ 8@\\x01",
    "{fn}{fn}{fn}{fn}{fn}{fn}",
    "++++++++++++++++++++++++++++++++++++++++++++++++++",
    "-),()-),()-),()-),()-),()-),()-),()",
    "face_cheekface_cheekface_cheekface_cheek",
    "\\x01\\x03\\x01\\x03\\x01\\x03\\x01\\x03",
    "쏃썸Ἇ\\x84",
    "詩夢詩夢詩夢詩夢詩夢詩夢0,0,0,0,0,0,0,0,0,0,0,0,0,0,0.59,0.871",
]


def test_real_lines_beat_noise() -> None:
    real = [hook_candidate_score(line, ocr_target=REAL_LINES[0]) for line in REAL_LINES]
    noise = [hook_candidate_score(line, ocr_target=REAL_LINES[0]) for line in NOISE_LINES]
    assert min(real) > max(noise), f"真台词 {real} 应全面高于噪声 {noise}"
    assert min(real) >= 0.5, f"真台词至少该有 0.5：{real}"
    assert max(noise) <= 0.25, f"噪声不该超过 0.25：{noise}"


def test_ocr_missing_does_not_change_order() -> None:
    real = hook_candidate_score(REAL_LINES[1])
    noise = hook_candidate_score(NOISE_LINES[1])
    assert real > noise, "没有 OCR 目标时也要能分出好坏"


def test_sample_count_is_weak_tiebreaker() -> None:
    low = hook_candidate_score(REAL_LINES[2], count=1)
    high = hook_candidate_score(REAL_LINES[2], count=400)
    assert 0 <= high - low <= 0.1, "采样次数只能是弱破局项"
