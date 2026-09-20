"""兼容层：netproxy 已搬到 `aurora.infra.netproxy`（P3.9），这里保留同名转发。"""
from __future__ import annotations

from aurora.infra.netproxy import (  # noqa: F401  (re-export)
    _state,
    set_settings_provider,
    _normalize,
    _env_proxy,
    _registry_proxy,
    bypass_list,
    resolve,
    current,
    build_opener,
    describe,
)
