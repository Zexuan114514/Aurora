"""悬浮窗更新必须是**非阻塞**的（2026-09-21 卡死事故的回归网）。

现场：`evaluate_js` 在窗口没就绪时会等 pywebview 的 `events.wait(20)`，
实测单次 20 秒；而悬浮窗在每个流式增量上都会被更新一次 —— 翻译链、桥接、
界面线程全被拖死（用户报「一句要等很久」「点按钮没反应」）。

现在 `update()` 只入队、由后台单线程合并推送；连续失败 3 次就停用悬浮窗。
"""
from __future__ import annotations

import threading
import time

from aurora.ui.overlay import Overlay


class FakeWindow:
    """假的 pywebview 窗口：可配置「每次 evaluate_js 很慢 / 直接抛异常」。"""

    def __init__(self, *, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.calls = 0
        self.lock = threading.Lock()
        self.scripts: list[str] = []

    def evaluate_js(self, script: str):
        with self.lock:
            self.calls += 1
        self.scripts.append(script)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("Main window failed to start")
        return None


def make_overlay(window, *, visible: bool = True) -> Overlay:
    overlay = Overlay(get_settings=lambda: {}, set_option=lambda *a, **k: None,
                      on_action=lambda *a, **k: None)
    overlay._window = window
    overlay._visible = visible
    return overlay


def wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_update_does_not_block_on_slow_window() -> None:
    window = FakeWindow(delay=0.6)
    overlay = make_overlay(window)
    start = time.perf_counter()
    overlay.update({"lines": {"translation": "测试"}})
    cost = time.perf_counter() - start
    assert cost < 0.1, f"update() 阻塞了 {cost:.2f}s —— 又变成同步等 GUI 了"
    assert wait_until(lambda: window.calls >= 1), "后台工作线程没把这次更新推出去"


def test_rapid_updates_are_coalesced() -> None:
    window = FakeWindow(delay=0.05)
    overlay = make_overlay(window)
    for index in range(40):
        overlay.update({"lines": {"translation": f"第 {index} 段"}})
    assert wait_until(lambda: overlay._pending == {}, timeout=5.0)
    time.sleep(0.3)
    assert window.calls < 40, f"40 次更新一次没合并（实际推了 {window.calls} 次）"
    assert window.scripts, "一次都没推出去"
    assert "第 39 段" in window.scripts[-1], "最后一帧必须是最新的内容"


def test_repeated_failures_disable_overlay() -> None:
    window = FakeWindow(fail=True)
    overlay = make_overlay(window)
    for index in range(6):
        overlay.update({"lines": {"translation": f"第 {index} 段"}})
        time.sleep(0.05)
    assert wait_until(lambda: overlay._disabled, timeout=6.0), "连续失败没有停用悬浮窗"
    assert overlay._window is None and not overlay._visible
    calls_when_disabled = window.calls
    overlay.update({"lines": {"translation": "停用之后"}})
    time.sleep(0.4)
    assert window.calls == calls_when_disabled, "停用后还在往 GUI 推"


def test_hidden_overlay_skips_gui() -> None:
    window = FakeWindow()
    overlay = make_overlay(window, visible=False)
    overlay.update({"lines": {"translation": "隐藏时不该推"}})
    time.sleep(0.4)
    assert window.calls == 0, "隐藏状态下仍然在往 GUI 推更新"
