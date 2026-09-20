"""签名播种用到的偏移表 / H-code 拼装（离线金样本）。

校准点：アマカノ３ 实测可用的码是 `HS65001#-6C@1B1F70:Amakano3.exe`，
它读的是挂钩点 RSP-0x70（伪 pushad 帧里的 R12）。Textractor 解析 H-code 时对
负偏移会再 `-= 4`（ITH 兼容），所以「真实栈偏移 -0x70」要写成 `-6C`。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gl import hookfinder  # noqa: E402


def test_real_offset_minus_0x70_becomes_code_minus_6c():
    code = hookfinder.build_code(module="Amakano3.exe", module_base=0x140000000,
                                 rip=0x1401B1F70, offset=-0x70, encoding="utf-8")
    assert code == "HS65001#-6C@1B1F70:Amakano3.exe"


def test_positive_offset_is_written_as_is():
    code = hookfinder.build_code(module="Amakano3.exe", module_base=0x140000000,
                                 rip=0x1401B1F70, offset=0x20, encoding="utf-8")
    assert code == "HS65001#20@1B1F70:Amakano3.exe"


def test_utf16_uses_q_mode():
    code = hookfinder.build_code(module="gdi.dll", module_base=0x10000000,
                                 rip=0x100004AA, offset=-0xC, encoding="utf-16")
    assert code == "HQ-8@4AA:gdi.dll"


def test_padding_is_emitted_before_offset():
    code = hookfinder.build_code(module="gdi.dll", module_base=0x10000000,
                                 rip=0x100004AA, offset=-0x28, padding=3,
                                 encoding="utf-8")
    assert code == "HS65001#3+-24@4AA:gdi.dll"


def test_reg_frame_matches_hook_offsets_table():
    """常用的几个寄存器必须在候选偏移表里（否则签名播种永远试不到它）。

    注：RSP/RBP 故意不进候选表 —— 它们指向栈帧本身，不会是文本指针。
    """
    candidates = set(hookfinder.HOOK_OFFSETS)
    for name in ("R12", "Rdx", "Rcx", "R8", "R9", "Rdi", "Rsi", "Rbx", "Rax"):
        off = hookfinder.REG_FRAME[name]
        assert off in candidates, f"{name} 的偏移 {off:#x} 不在 HOOK_OFFSETS 里"
    # 实测命中的那个寄存器排在最前面
    assert hookfinder.HOOK_OFFSETS[0] == hookfinder.REG_FRAME["R12"] == -0x70


def test_signature_table_prefers_unique_artemis_variant():
    names = [name for name, _ in hookfinder.TEXT_FUNC_SIGNATURES]
    assert names[0] == "artemis64"
    blobs = dict(hookfinder.TEXT_FUNC_SIGNATURES)
    assert blobs["artemis64"].hex().upper() == \
        "48895C24205556574154415541564157488BEC"
