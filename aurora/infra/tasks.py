"""任务执行器：命名、有界、可取消（P3.6）。

替代散落的 `threading.Thread(...).start()`：后台任务都有名字、可查询、可协作取消，
退出时统一 `shutdown()`。只用标准库，不引入新依赖。
"""
from __future__ import annotations

import threading
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures.thread import _worker
from typing import Callable


class _DaemonExecutor(ThreadPoolExecutor):
    """工作线程设为 daemon：进程退出时不会被没结束的任务卡住。

    标准库默认是非 daemon 线程，任何忘记调 `shutdown()` 的调用方都会挂住解释器退出
    （实测 tools/session_probe.py 就被卡住）。这里照 CPython 的 `_adjust_thread_count`
    复制一份，只把 thread.daemon 打开。
    """

    def _adjust_thread_count(self) -> None:      # pragma: no cover - 依据标准库实现
        if self._idle_semaphore.acquire(timeout=0):
            return
        if len(self._threads) >= self._max_workers:
            return
        queue = self._work_queue

        def weakref_cb(_ref, q=queue):
            q.put(None)

        thread = threading.Thread(
            name=f"{self._thread_name_prefix or 'aurora-task'}_{len(self._threads)}",
            target=_worker,
            args=(weakref.ref(self, weakref_cb), queue, self._initializer, self._initargs))
        thread.daemon = True
        thread.start()
        self._threads.add(thread)


class TaskRunner:
    """命名任务注册表 + 有界线程池。"""

    def __init__(self, *, max_workers: int = 8, name_prefix: str = "aurora-task") -> None:
        self._executor = _DaemonExecutor(max_workers=max_workers, thread_name_prefix=name_prefix)
        self._lock = threading.RLock()
        self._futures: dict[str, Future] = {}
        self._tokens: dict[str, threading.Event] = {}
        self._services: dict[str, threading.Thread] = {}
        self._name_prefix = name_prefix

    def submit(self, name: str, fn: Callable, *args, **kwargs) -> Future:
        """提交命名任务；同名任务会先取消旧的。"""
        self.cancel(name)
        token = threading.Event()
        with self._lock:
            self._tokens[name] = token
        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures[name] = future
        future.add_done_callback(lambda _f, key=name: self._forget(key))
        return future

    def token(self, name: str) -> threading.Event:
        """取任务取消令牌（协作取消：任务自己检查 `token.is_set()`）。"""
        with self._lock:
            if name not in self._tokens:
                self._tokens[name] = threading.Event()
            return self._tokens[name]

    def spawn(self, name: str, target: Callable, *args, thread_name: str = "", **kwargs) -> threading.Thread:
        """起一条**长驻服务线程**（daemon），同样登记进本 runner。

        与 `submit()` 的分工：`submit` 走有界线程池，适合短任务；`spawn` 给一直在跑的
        服务循环（会话监控 / 翻译队列 / 托盘 / 热键 / OCR 采样…），避免长驻任务把池占满。
        取消同样走协作令牌（`token(name)`）。
        """
        self.cancel(name)
        self.token(name)
        thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True,
                                  name=thread_name or f"{self._name_prefix}-{name}")
        with self._lock:
            self._services[name] = thread
        thread.start()
        return thread

    def is_running(self, name: str) -> bool:
        with self._lock:
            thread = self._services.get(name)
            if thread is not None and thread.is_alive():
                return True
            future = self._futures.get(name)
            return bool(future and not future.done())

    def cancel(self, name: str) -> bool:
        """取消任务：置协作令牌 + 尝试撤销尚未开始的任务。"""
        with self._lock:
            token = self._tokens.get(name)
            future = self._futures.pop(name, None)
        if token is not None:
            token.set()
        cancelled = future.cancel() if future is not None else False
        return bool(cancelled or token is not None)

    def cancel_all(self) -> int:
        with self._lock:
            names = list(self._tokens)
        return sum(1 for name in names if self.cancel(name))

    def active(self) -> list[str]:
        with self._lock:
            running = {n for n, f in self._futures.items() if not f.done()}
            running |= {n for n, t in self._services.items() if t.is_alive()}
            return sorted(running)

    def stats(self) -> dict:
        with self._lock:
            return {"active": self.active(), "known": sorted(self._tokens),
                    "max_workers": self._executor._max_workers}

    def shutdown(self, *, grace: float = 3.0) -> None:
        """取消全部任务并关停线程池（应用退出时调用）。"""
        self.cancel_all()
        with self._lock:
            services = list(self._services.values())
        for thread in services:
            thread.join(timeout=max(0.0, grace / max(1, len(services))))
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _forget(self, name: str) -> None:
        with self._lock:
            self._futures.pop(name, None)


_DEFAULT: TaskRunner | None = None


def default_runner() -> TaskRunner:
    """进程级默认 runner：给不便注入 runner 的叶子模块用（退出时统一关停）。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = TaskRunner(max_workers=8, name_prefix="aurora-svc")
    return _DEFAULT
