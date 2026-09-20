"""会话计时规则（纯函数）：游玩时长口径、崩溃恢复补记与入账阈值。

P1 分层时从 `gl/process.py::ProcessManager._finalize` 与 `gl/api.py::_recover_sessions`
里把公式抽出来；行为由 `tests/fixtures/golden/session_rules.golden.json` 卡住。
"""
from __future__ import annotations


def session_seconds(*, started_at: float, ended_at: float = 0.0, gone_at: float = 0.0,
                    now: float = 0.0) -> float:
    """一次会话的时长（秒）。

    - 以「游戏本体真正消失的时刻」结算，`gone_at` 优先于 `ended_at`，都没有再用 `now`；
    - `started_at` 缺失（0）时口径为 0，不把整段时间算进玩家时长；
    - 结果不小于 0。
    """
    end = float(gone_at or ended_at or now)
    start = float(started_at or 0.0) or end
    return max(0.0, end - start)


def recovered_seconds(*, started_at: int, heartbeat: int, now: int) -> int:
    """启动器先退出、游戏后结束时的补记时长（秒）。

    以最后一次心跳为准；心跳晚于 `now`（时钟回拨等）时按 `now` 截断；负数夹到 0。
    心跳缺失时回退成起始时间，即补记 0 秒。
    """
    start = int(started_at or 0)
    beat = int(heartbeat or 0) or start
    return max(0, min(beat, int(now)) - start)


def is_countable(seconds: float, threshold: float) -> bool:
    """这段时长够不够入账（`gl/api.py` 里原为 `seconds >= HEARTBEAT_SECONDS`）。"""
    return float(seconds) >= float(threshold)
