"""兼容层：linetrans 已搬到 `aurora.infra.linetrans`（P3.9），这里保留同名转发。"""
from __future__ import annotations

from aurora.infra.linetrans import (  # noqa: F401  (re-export)
    MAX_HISTORY,
    SYSTEM_PROMPT,
    _glossary_path,
    load_glossary,
    save_glossary,
    glossary_terms,
    LineTranslator,
    build_messages,
    stream_llm,
)
