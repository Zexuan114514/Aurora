"""翻译自检：语言检测 + provider 链路 + 缓存。结果写入 UTF-8 报告。

默认只测免费接口；设置 AURORA_TRANSLATE_KEY 后额外测 LLM 接口。
可选环境变量：AURORA_TRANSLATE_BASE / AURORA_TRANSLATE_MODEL。
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gl import translate  # noqa: E402

REPORT = Path(__file__).resolve().parent / "translate-report.txt"

DETECT_CASES = [
    ("主播女孩重度依赖是一款多结局ADV。", "zh"),
    ("It was about 100 years ago, in the 10th year of the Taishou era.", "en"),
    ("これはテストです。とても面白い物語。", "ja"),
    ("", "empty"),
    ("12345 !!!", "other"),
]

SAMPLE = ("The story follows a young swordsman who must protect his hometown "
          "from an invading army.")


def main() -> int:
    out = io.StringIO()

    def write(line: str = "") -> None:
        out.write(line + "\n")

    write("Aurora 简介翻译自检")
    write("=" * 48)
    ok = True

    write("\n[语言检测]")
    for text, want in DETECT_CASES:
        got = translate.detect_language(text)
        if got != want:
            ok = False
        write(f"  {'OK ' if got == want else 'BAD'} want={want:5} got={got:5} <- {text[:34]!r}")

    write("\n[needs_translation]")
    for text, want in [("中文简介，描述游戏内容。", False), (SAMPLE, True)]:
        got = translate.needs_translation(text)
        if got != want:
            ok = False
        write(f"  {'OK ' if got == want else 'BAD'} {got} (want {want})")

    settings = {"translate_provider": "free"}
    write("\n[provider 链路 / 免费接口]")
    t0 = time.time()
    res = translate.translate_text(SAMPLE, settings=settings)
    live = time.time() - t0
    write(f"  provider={res['provider']} changed={res['changed']} lang={res['lang']} ({live:.2f}s)")
    write(f"  text: {res['text']}")
    if not res["changed"]:
        ok = False
        write("  BAD 免费接口没有返回译文")

    write("\n[缓存]")
    t0 = time.time()
    res2 = translate.translate_text(SAMPLE, settings=settings)
    cached = time.time() - t0
    hit = cached < max(live / 2, 0.2)
    write(f"  二次调用 {cached:.3f}s -> {'命中缓存' if hit else '疑似未命中'}")
    if res2["text"] != res["text"]:
        ok = False
        write("  BAD 缓存结果与首次不一致")

    key = os.environ.get("AURORA_TRANSLATE_KEY", "").strip()
    if key:
        write("\n[provider 链路 / LLM 接口]")
        llm = translate.translate_text(SAMPLE, settings={
            "translate_provider": "llm",
            "translate_api_key": key,
            "translate_base_url": os.environ.get("AURORA_TRANSLATE_BASE",
                                                 "https://api.deepseek.com"),
            "translate_model": os.environ.get("AURORA_TRANSLATE_MODEL", "deepseek-chat"),
        })
        write(f"  provider={llm['provider']} changed={llm['changed']}")
        write(f"  text: {llm['text']}")
        if not llm["changed"]:
            ok = False
            write("  BAD LLM 接口没有返回译文")
    else:
        write("\n[provider 链路 / LLM 接口] 跳过（未设置 AURORA_TRANSLATE_KEY）")

    write("\n结论: " + ("全部通过" if ok else "存在失败项"))
    text = out.getvalue()
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
