"""兼容层：匹配与打分已搬到 `aurora.domain.matching`（P1），这里保留同名转发。"""
from __future__ import annotations

from aurora.domain.matching import (  # noqa: F401  (re-export)
    GENERIC_DIRS,
    NOISE,
    _EXT_NOISE,
    _BRACKETS,
    _KEEP,
    _SEP,
    _CAMEL,
    _CJK,
    _TRAIL_YEAR,
    has_cjk,
    _clean_name,
    norm,
    tokens,
    _is_meaningful,
    describe_path,
    _variants,
    similarity,
    score_candidate,
)
