"""Windows 自带 OCR（Windows.Media.Ocr）。

只依赖按命名空间拆分的 winrt 包（MIT，每个几十 KB），不用 Tesseract/PaddleOCR，
所以 exe 体积几乎不变。日语识别需要系统安装「日语 OCR」组件，缺了会返回
`no-language`，由界面给出安装指引。
"""
from __future__ import annotations

import asyncio
import importlib
import struct
import threading
import time

_lock = threading.RLock()
_engines: dict[str, object] = {}
_langs: tuple[str, ...] | None = None
_import_error = ""


def _mods():
    """按需导入 winrt 模块；没装就返回 None（功能降级，不影响启动）。"""
    global _import_error
    try:
        return (
            importlib.import_module("winrt.windows.media.ocr"),
            importlib.import_module("winrt.windows.graphics.imaging"),
            importlib.import_module("winrt.windows.storage.streams"),
            importlib.import_module("winrt.windows.globalization"),
        )
    except Exception as exc:      # pragma: no cover - 取决于运行环境
        _import_error = f"{type(exc).__name__}: {exc}"
        return None


def available() -> bool:
    return _mods() is not None


def languages() -> list[str]:
    global _langs
    with _lock:
        if _langs is not None:
            return list(_langs)
        mods = _mods()
        if not mods:
            _langs = ()
            return []
        ocr_mod = mods[0]
        try:
            _langs = tuple(l.language_tag for l in ocr_mod.OcrEngine.available_recognizer_languages)
        except Exception:
            _langs = ()
        return list(_langs)


def has_language(lang: str = "ja-JP") -> bool:
    """系统里有没有这个语言的 OCR 引擎。

    注意：Windows 报的是 `ja`，我们请求的是 `ja-JP`（实测 AvailableRecognizerLanguages
    返回 ['en-US', 'ja', 'zh-Hans-CN']，但 try_create_from_language('ja-JP') 是能成的）。
    只比字符串会把已经装了日语 OCR 的机器误判成「没装」，所以按主语言子标签比。
    """
    want = str(lang or "").lower().replace("_", "-")
    want_primary = want.split("-")[0]
    for item in languages():
        have = str(item or "").lower().replace("_", "-")
        if have == want or have.split("-")[0] == want_primary:
            return True
    return False


def real_tag(lang: str = "ja-JP") -> str:
    """系统里实际可用的语言标签（`ja-JP` → `ja`），没有就用原样。"""
    want = str(lang or "").lower().replace("_", "-")
    for item in languages():
        have = str(item or "").lower().replace("_", "-")
        if have == want or have.split("-")[0] == want.split("-")[0]:
            return item
    return lang


def status(lang: str = "ja-JP") -> dict:
    mods = _mods()
    return {
        "available": mods is not None,
        "languages": languages(),
        "lang": lang,
        "lang_ready": has_language(lang),
        "error": _import_error,
    }


def _engine(lang: str):
    lang = real_tag(lang)          # ja-JP → 系统里的 ja，否则 try_create 会返回 None
    with _lock:
        if lang in _engines:
            return _engines[lang]
        mods = _mods()
        if not mods:
            return None
        ocr_mod, _, _, glob_mod = mods
        try:
            engine = ocr_mod.OcrEngine.try_create_from_language(glob_mod.Language(lang))
        except Exception:
            engine = None
        if engine is not None:
            _engines[lang] = engine
        return engine


def bmp_bytes(bgr: bytes, width: int, height: int) -> bytes:
    """把自下而上的 24 位 BGR 像素包成 BMP（不需要 Pillow）。"""
    row = width * 3
    pad = (-row) % 4
    stride = row + pad
    pixels = bytearray()
    for y in range(height - 1, -1, -1):          # BMP 自下而上
        start = y * row
        pixels += bgr[start:start + row]
        pixels += b"\x00" * pad
    header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels),
                       2835, 2835, 0, 0)
    return bytes(header + info + bytes(pixels))


async def _recognize_async(payload: bytes, lang: str) -> str:
    _, imaging, streams, _ = _mods()
    engine = _engine(lang)
    if engine is None:
        raise RuntimeError("no-language")
    stream = streams.InMemoryRandomAccessStream()
    writer = streams.DataWriter(stream)
    writer.write_bytes(payload)
    await writer.store_async()
    stream.seek(0)
    decoder = await imaging.BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    return result.text


def recognize_bgr(bgr: bytes, width: int, height: int, lang: str = "ja-JP") -> dict:
    """识别一张 BGR 位图，返回 {ok, text, ms, error}。"""
    started = time.time()
    if not bgr or width <= 0 or height <= 0:
        return {"ok": False, "error": "empty", "text": "", "ms": 0}
    if not available():
        return {"ok": False, "error": "no-winrt", "text": "", "ms": 0}
    if not has_language(lang):
        return {"ok": False, "error": "no-language", "text": "", "ms": 0}
    try:
        payload = bmp_bytes(bgr, width, height)
        text = asyncio.run(_recognize_async(payload, lang))
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc), "text": "", "ms": 0}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "text": "", "ms": 0}
    return {"ok": True, "error": "", "text": text,
            "ms": int((time.time() - started) * 1000)}
