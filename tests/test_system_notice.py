"""系统/驱动提示不算台词（真机样本：DRACU RIOT 的覆盖模式提示）。

2026-09-21 真机自测里，Textractor 抓到
`モードのオーバーレイをデバイスがサポートしていません。`（D3D 覆盖模式不支持的提示），
它有假名、有句号，形态上完全像台词，于是被送去翻译了。这条规则按「技术口吻 + 技术
名词」判定，并且必须**同时**出现才算，免得误伤剧情（「デバイスって何？」这种不算）。
"""
from __future__ import annotations

import pytest

from aurora.domain import text_rules

#: 真机抓到的那一条
REAL_NOTICE = "モードのオーバーレイをデバイスがサポートしていません。"


@pytest.mark.parametrize("line", [
    REAL_NOTICE,
    "ご使用の環境では DirectX の初期化に失敗しました。",
    "サウンドデバイスが応答していません。",
    "D3D11.dll の読み込みに失敗しました。",
])
def test_system_notice_is_noise(line: str) -> None:
    assert text_rules.looks_like_system_notice(line)
    assert text_rules.looks_like_noise(line)
    assert not text_rules.looks_like_dialogue(line)


@pytest.mark.parametrize("line", [
    "そんなの、サポートしていませんよ。",        # 剧情里人也可能这么说（没有技术主语）
    "デバイスって何のこと？",
    "ファイルはどこにあるの？",
    "モードを切り替えたら、彼女は少しだけ笑った。",
])
def test_dialogue_is_not_noise(line: str) -> None:
    assert not text_rules.looks_like_system_notice(line)
    assert not text_rules.looks_like_noise(line)
