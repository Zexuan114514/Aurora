"""冷启动宽限期（2026-09-22 遗留项二）。

现场：游戏刚起来、领跑线程还没选出来时连点翻页，前几句台词先从不那么「强」的线程到
（没句读、或暂时不是领跑线程），被线程门禁整句丢掉 —— 真机自测里「原始行审计漏掉
N 条」就是这么来的（那些行逐条过清洗规则都是正经台词）。

现在：会话开始后 `COLD_START_GRACE` 秒内只挡「不像台词」的行，台词照收；去重/并合
照常做，所以同一句从两条线程来仍然只翻一次。宽限期只对走过 `start()` 的会话生效
（自检脚本直接喂行时行为不变）。
"""
from __future__ import annotations

import time

from aurora.infra import vntext

#: 没句读、但明显是台词的「弱行」（门禁的弱点就在这类行上）
WEAK_DIALOGUE = "バッカ、お前、今から楽園に行くんだぜ"
#: 不像台词的行（菜单/系统提示之类）：宽限期内也必须挡
NOT_DIALOGUE = "迷宮探索中継続表示切替案内"


def make_engine(seen: list) -> vntext.VnTextEngine:
    engine = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                 on_line=seen.append)
    now = time.time()
    engine._started_at = now
    engine._seen = {
        "leader": {"name": "KiriKiriZ", "code": "", "count": 9, "sample": "",
                   "dialogue": 9, "prose": 9, "last_seen": now},
        "other": {"name": "TextOutW", "code": "", "count": 3, "sample": "",
                  "dialogue": 3, "prose": 1, "last_seen": now},
    }
    engine._leader = "leader"
    return engine


def promote(engine: vntext.VnTextEngine, key: str, text: str) -> None:
    engine._promote({"key": key, "clean": text,
                     "norm": vntext.normalize_for_dedupe(text),
                     "text": text, "probe": text})


def test_cold_start_keeps_dialogue_from_a_non_leader_thread() -> None:
    seen: list = []
    engine = make_engine(seen)
    promote(engine, "other", WEAK_DIALOGUE)
    assert [row["text"] for row in seen] == [WEAK_DIALOGUE], \
        "冷启动宽限期内，非领跑线程的台词不该被门禁丢掉"
    assert engine.status()["cold_passes"] == 1
    assert engine.status()["gated"] == 0


def test_after_the_grace_the_same_line_is_gated_again() -> None:
    seen: list = []
    engine = make_engine(seen)
    engine._started_at = time.time() - (engine.COLD_START_GRACE + 1)
    promote(engine, "other", WEAK_DIALOGUE)
    assert seen == [], "宽限期过了，非领跑线程的弱行照旧要挡"
    assert engine.status()["gated"] == 1


def test_cold_start_still_blocks_lines_that_do_not_look_like_dialogue() -> None:
    seen: list = []
    engine = make_engine(seen)
    promote(engine, "other", NOT_DIALOGUE)
    assert seen == [], "不像台词的行不受宽限期保护"
    assert engine.status()["gated"] == 1


def test_no_grace_when_the_session_never_started() -> None:
    seen: list = []
    engine = make_engine(seen)
    engine._started_at = 0.0                    # 自检脚本直接喂行的场景
    promote(engine, "other", WEAK_DIALOGUE)
    assert seen == []
    assert engine.status()["gated"] == 1
