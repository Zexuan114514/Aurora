"""P3.6：任务执行器与事件总线的行为契约（离线）。"""
from __future__ import annotations

import pathlib
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.app.events import EventBus          # noqa: E402
from aurora.infra.tasks import TaskRunner, default_runner   # noqa: E402


def test_runner_submit_and_active() -> None:
    runner = TaskRunner(max_workers=2)
    started, release = threading.Event(), threading.Event()
    runner.submit("wait", lambda: (started.set(), release.wait(5)))
    assert started.wait(5)
    assert "wait" in runner.active()
    release.set()
    time.sleep(0.2)
    assert "wait" not in runner.active()
    runner.shutdown()


def test_runner_cancel_token() -> None:
    runner = TaskRunner(max_workers=1)
    token = runner.token("job")
    assert not token.is_set()
    assert runner.cancel("job") is True
    assert token.is_set(), "协作取消必须置位令牌"
    runner.shutdown()


def test_runner_spawn_registers_service_thread() -> None:
    """长驻服务线程：登记进 runner、daemon、可协作取消。"""
    runner = TaskRunner(max_workers=2)
    seen: list[str] = []

    def service() -> None:
        token = runner.token("svc.loop")
        while not token.is_set():
            seen.append("tick")
            time.sleep(0.05)

    thread = runner.spawn("svc.loop", service, thread_name="aurora-test-svc")
    assert thread.daemon is True, "服务线程必须是 daemon，否则会卡住进程退出"
    time.sleep(0.2)
    assert "svc.loop" in runner.active() and runner.is_running("svc.loop")
    runner.cancel("svc.loop")
    thread.join(timeout=2)
    assert not thread.is_alive(), "取消令牌后服务循环必须退出"
    assert runner.is_running("svc.loop") is False
    runner.shutdown()


def test_default_runner_is_singleton() -> None:
    assert default_runner() is default_runner()


def test_event_bus_envelope_and_order() -> None:
    bus = EventBus(clock=lambda: 1234.0)
    got: list[dict] = []
    bus.subscribe("game:running", got.append)
    first = bus.publish("game:running", {"game_id": "g1"})
    second = bus.publish("game:running", {"game_id": "g2"})
    assert (first["seq"], second["seq"]) == (1, 2), "seq 必须单调递增"
    assert first["ts"] == 1234 and first["topic"] == "game:running"
    assert [row["payload"]["game_id"] for row in got] == ["g1", "g2"]


def test_event_bus_unsubscribe_and_wildcard() -> None:
    bus = EventBus()
    seen: list[str] = []
    unsubscribe = bus.subscribe("vntext:line", lambda env: seen.append("line"))
    bus.subscribe("*", lambda env: seen.append(env["topic"]))
    bus.publish("vntext:line", {"text": "a"})
    unsubscribe()
    bus.publish("vntext:line", {"text": "b"})
    assert seen == ["line", "vntext:line", "vntext:line"]


def test_event_bus_isolates_subscriber_errors() -> None:
    bus = EventBus()
    ok: list[dict] = []
    bus.subscribe("x", lambda env: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe("x", ok.append)
    bus.publish("x", {})
    assert len(ok) == 1, "一个订阅者抛错不能影响其它订阅者"
    assert bus.errors and "boom" in bus.errors[0]
