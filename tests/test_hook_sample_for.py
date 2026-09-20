"""找钩子验证用的线程取样：必须扫全量线程表，不能被界面投影的前 12 条截断。

真机背景（アマカノ３，2026-09-20 20:47 那次）：游戏里挂着一条每帧吐乱码的坏码，
引擎 `_seen` 里堆了几百条垃圾线程；候选钩子码的线程行数只有 1，按行数排序永远
进不了 `status()["threads"][:12]`，于是「每个候选都读不到文本」→ 找钩子全线失败。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aurora.infra.vntext import VnTextEngine  # noqa: E402

CODE = "HS65001#-6C@1B1F70:Amakano3.exe"


def _engine() -> VnTextEngine:
    return VnTextEngine(settings_getter=lambda: {}, on_line=None, on_status=None)


def _seed(engine: VnTextEngine) -> None:
    """造 200 条刷屏垃圾线程（行数很高）+ 1 条候选线程（行数 1、样例是真台词）。"""
    with engine._lock:
        for index in range(200):
            engine._seen[f"garbage:{index}"] = {
                "name": f"垃圾{index}", "code": "HS65001#20@38A78:emotedriver.dll",
                "count": 500 + index, "sample": "", "dialogue": 0,
                "last_seen": 0.0, "raw": "\ufffd\\x18\x10F",
            }
        engine._seen["hook:1B1F70"] = {
            "name": "UserHook1", "code": CODE, "count": 1,
            "sample": "詩夢「……これで、落ちたら」", "dialogue": 1,
            "last_seen": 0.0,
        }


def test_status_projection_is_truncated_to_12():
    """确认前提：界面投影确实会把候选线程挤掉（不然这条测试就没意义）。"""
    engine = _engine()
    _seed(engine)
    rows = engine.status()["threads"]
    assert len(rows) == 12
    assert all(row["code"] != CODE for row in rows)


def test_hook_sample_for_scans_full_thread_table():
    engine = _engine()
    _seed(engine)
    assert engine.hook_sample_for(CODE) == "詩夢「……これで、落ちたら」"


def test_hook_sample_for_falls_back_to_raw_text():
    """候选码吐的东西可能过不了清洗（没进 sample），那就用原始文本兜底。"""
    engine = _engine()
    with engine._lock:
        engine._seen["hook:raw"] = {
            "name": "UserHook2", "code": CODE, "count": 1, "sample": "",
            "dialogue": 0, "last_seen": 0.0, "raw": "明らかに、詩夢の顔が青い。",
        }
    assert engine.hook_sample_for(CODE) == "明らかに、詩夢の顔が青い。"


def test_hook_sample_for_prefers_newest_thread():
    """每翻一页 Textractor 会换一个线程句柄：要取最新那条，不是最长那条。

    真机背景：确认轮里旧句子更长时，按长度取会一直返回旧文本，于是「文本没变」
    → 确认轮判 0/2 → 明明能用的码被丢掉。
    """
    engine = _engine()
    with engine._lock:
        engine._seen["hook:old"] = {
            "name": "UserHook1", "code": CODE, "count": 1,
            "sample": "とても長い前の台詞です、こんなに長いのに古いのです。",
            "dialogue": 1, "last_seen": 100.0,
        }
        engine._seen["hook:new"] = {
            "name": "UserHook1", "code": CODE, "count": 1,
            "sample": "新しい台詞。", "dialogue": 1, "last_seen": 200.0,
        }
    assert engine.hook_sample_for(CODE) == "新しい台詞。"


def test_hook_sample_for_skips_pseudo_threads():
    engine = _engine()
    with engine._lock:
        engine._seen["clip"] = {
            "name": "剪贴板", "code": CODE, "count": 9,
            "sample": "https://github.com/hanmin0822/MisakaHookFinder",
            "dialogue": 0, "last_seen": 0.0,
        }
    assert engine.hook_sample_for(CODE) == ""
