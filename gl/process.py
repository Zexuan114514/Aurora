"""兼容层：process 已搬到 `aurora.infra.process`（P3.9-d），这里保留同名转发。"""
from __future__ import annotations

from aurora.infra.process import (  # noqa: F401  (re-export)
    CREATE_NEW_PROCESS_GROUP,
    DETACHED_PROCESS,
    CREATE_BREAKAWAY_FROM_JOB,
    PROCESS_QUERY_LIMITED_INFORMATION,
    SYNCHRONIZE,
    WAIT_TIMEOUT,
    INFINITE,
    _kernel32,
    _open,
    process_image,
    pid_matches,
    ForeignProcess,
    POLL_SECONDS,
    STARTUP_GRACE,
    EXIT_GRACE,
    ProcessManager,
    _split_args,
    reveal,
)
