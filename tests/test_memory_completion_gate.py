"""缺字补全的引擎门禁（2026-09-21 深夜事故的回归网）。

现场：DRACU RIOT / Cafe Stella / 白色相簿2 这些**有引擎级钩子**的游戏，正文本来就
完整，可同进程里还挂着按字形抓的 GDI 钩子线程 —— 那些线程触发了缺字补全：一句扫
70 秒、每来一句就新起一个扫描线程并行抢 GIL，取词/翻译/界面全被拖死（「翻页后半天
不出文本、按停止翻译才一股脑涌出来」），还补出 `耀「理由は…` 这种带缓冲垃圾的错句。

反例（必须保留补全）：WillPlus/AdvHD 只能按字形抓字，确实缺字；Artemis/Emote 的
用户钩子码给出的正文本身也缺字（实测 アマカノ３ 靠补全才完整）。
"""
from __future__ import annotations

from aurora.infra import vntext


def make_engine() -> vntext.VnTextEngine:
    engine = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                 on_line=lambda row: None)
    engine._pid = 1234          # 有 pid 才会考虑补全
    engine._seen["gdi"] = {"name": "TextOutW", "code": "", "count": 1,
                           "sample": "", "dialogue": 1, "last_seen": 0.0}
    return engine


def promote(engine: vntext.VnTextEngine, clean: str) -> None:
    engine._promote({"key": "gdi", "clean": clean,
                     "norm": vntext.normalize_for_dedupe(clean),
                     "text": clean, "probe": clean})


def test_engine_hook_games_skip_memory_completion() -> None:
    for name in ("TVP/KIRIKIRI", "Leaf", "BGI/Ethornell", "Escu:de", "Siglus",
                 "CatSystem2/Ares"):
        engine = make_engine()
        engine._engine = name
        calls: list[str] = []
        engine._complete_from_memory = lambda text, box=calls: box.append(text) or ""
        promote(engine, "「理由はいくつかあるが……」")
        assert calls == [], f"{name} 不该去扫内存补全（正文本来就完整）"


def test_glyph_only_engines_still_complete() -> None:
    for name in ("WillPlus", "Artemis/Emote", ""):
        engine = make_engine()
        engine._engine = name
        calls: list[str] = []
        engine._complete_from_memory = lambda text, box=calls: box.append(text) or ""
        promote(engine, "家近離心倒")
        assert calls == ["家近離心倒"], f"{name or '(未识别)'} 的缺字版应该去内存里补全"


def test_non_glyph_hook_never_completes() -> None:
    engine = make_engine()
    engine._engine = "WillPlus"
    engine._seen["gdi"]["name"] = "KiriKiriZ"          # 引擎钩子原文，不缺字
    calls: list[str] = []
    engine._complete_from_memory = lambda text, box=calls: box.append(text) or ""
    promote(engine, "家近離心倒")
    assert calls == []
