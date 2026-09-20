"""进程内事件总线：`{topic, seq, ts, payload}`（见 docs/architecture/contracts/events.md）。

替代构造器回调（`on_line` / `on_status` / `on_found` / `on_exit`）：发布方只管发，
订阅方各自处理；单个订阅者抛异常不影响发布方与其它订阅者。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

Handler = Callable[[dict], None]
MAX_RECENT = 200


class EventBus:
    """线程安全的发布订阅；`recent()` 保留最近若干条信封供诊断用。"""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._seq = 0
        self._subs: dict[str, list[Handler]] = {}
        self._recent: list[dict] = []
        self.errors: list[str] = []

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        """订阅主题；返回取消订阅的函数。`"*"` 表示订阅全部主题。"""
        with self._lock:
            self._subs.setdefault(topic, []).append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._subs.get(topic) or []
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def publish(self, topic: str, payload: dict | None = None) -> dict:
        """发布事件并返回信封（`seq` 单调递增）。"""
        with self._lock:
            self._seq += 1
            envelope = {"topic": topic, "seq": self._seq,
                        "ts": int(self._clock()), "payload": dict(payload or {})}
            handlers = list(self._subs.get(topic) or []) + list(self._subs.get("*") or [])
            self._recent.append(envelope)
            if len(self._recent) > MAX_RECENT:
                self._recent = self._recent[-MAX_RECENT:]
        for handler in handlers:
            try:
                handler(envelope)
            except Exception as exc:
                with self._lock:
                    self.errors.append(f"{topic}: {type(exc).__name__}: {exc}")
        return envelope

    def recent(self, limit: int = MAX_RECENT) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._recent[-max(1, limit):]]

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()
            self._recent.clear()
            self._seq = 0
