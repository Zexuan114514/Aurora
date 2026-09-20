"""兼容层：downloads 已搬到 `aurora.infra.downloads`（P3.9-c），这里保留同名转发。"""
from __future__ import annotations

from aurora.infra.downloads import (  # noqa: F401  (re-export)
    TEMP_SUFFIXES,
    ARCHIVE_SUFFIXES,
    POLL_SECONDS,
    STABLE_HITS,
    find_extractor,
    _norm_name,
    _flatten,
    _extract_zip,
    extract,
    DownloadWatcher,
)
