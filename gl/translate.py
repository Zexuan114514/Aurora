"""游戏简介翻译。

策略：OpenAI 兼容的 LLM 接口为主，免费免 Key 接口兜底，任何失败都退化为保留原文。
只依赖标准库（经 gl/sources/net.py 发请求），不引入新依赖。
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse

from .sources.net import cache_get, cache_put, clean_html, fetch_json

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
TARGET_DEFAULT = "zh-CN"
#: 翻译结果缓存一年（内容不变就不重复计费）
TRANSLATE_TTL = 365 * 24 * 3600
#: 简介硬上限，防止意外传入长文本
_MAX_INPUT = 500

#: 免费兜底：MyMemory（国内可直连；Google 被墙故不用）
FREE_ENDPOINT = "https://api.mymemory.translated.net/get"

SYSTEM_PROMPT = (
    "你是专业的游戏本地化译者。把用户给出的游戏简介翻译成简体中文，"
    "只输出译文本身，不要解释、不要加引号、不要保留原文、不要使用 Markdown 代码块。"
)

# --------------------------------------------------------------------------- #
# 语言检测
# --------------------------------------------------------------------------- #
_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]")      # 平假名 / 片假名
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")       # 汉字（不含假名）
_LATIN = re.compile(r"[A-Za-z]")
_QUOTES = "\"'“”‘’「」『』"


def detect_language(text: str) -> str:
    """粗略判断简介语言，返回 zh / ja / en / other / empty。

    注意：不能用 detect.has_cjk —— 它的正则包含假名，会把日文误判成中文。
    """
    t = (text or "").strip()
    if not t:
        return "empty"
    kana = len(_KANA.findall(t))
    han = len(_HAN.findall(t))
    latin = len(_LATIN.findall(t))
    if kana >= 3:
        return "ja"
    if han >= 4 and han >= latin:
        return "zh"
    if latin >= 8:
        return "en"
    if han >= 4:
        return "zh"
    return "other"


def needs_translation(text: str, target: str = TARGET_DEFAULT) -> bool:
    """简介是否需要用目标语言重写（目前只支持中文目标）。"""
    lang = detect_language(text)
    if lang == "empty":
        return False
    if (target or "").lower().startswith("zh"):
        return lang != "zh"
    return True


# --------------------------------------------------------------------------- #
# 文本清洗
# --------------------------------------------------------------------------- #
def _clean_output(raw: str) -> str:
    out = (raw or "").strip()
    if not out:
        return ""
    if out.startswith("```"):
        out = re.sub(r"^```[a-zA-Z0-9]*\s*", "", out)
        out = re.sub(r"\s*```$", "", out).strip()
    if len(out) >= 2 and out[0] in _QUOTES and out[-1] in _QUOTES:
        out = out[1:-1].strip()
    return out


def _looks_translated(out: str, target: str) -> bool:
    """目标为中文时，译文至少要含汉字，否则视为失败。"""
    if (target or "").lower().startswith("zh"):
        return bool(_HAN.search(out or ""))
    return bool(out)


def _truncate(text: str, limit: int) -> str:
    """超长简介按句子边界截断并加省略号，避免译文停在半个句子上。"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("。", "！", "？", "\n", "；", ". ", "! ", "? ", "; "):
        cut = head.rfind(sep)
        if cut >= limit * 0.6:
            return head[:cut + len(sep)].rstrip() + "…"
    return head.rstrip() + "…"


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
def llm_translate(text: str, *, target: str = TARGET_DEFAULT,
                  settings: dict | None = None, timeout: float = 30.0) -> str | None:
    """OpenAI 兼容的 chat/completions 接口。未配置 Key 或调用失败返回 None。"""
    cfg = settings or {}
    key = str(cfg.get("translate_api_key") or "").strip()
    if not key:
        return None
    base = str(cfg.get("translate_base_url") or "https://api.deepseek.com").strip().rstrip("/")
    if not base:
        return None
    model = str(cfg.get("translate_model") or "deepseek-chat").strip() or "deepseek-chat"
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"

    body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    # attempts=1：LLM 调用失败重试成本高（重复计费），交给上层兜底
    data = fetch_json(url, method="POST", body=body, timeout=timeout, attempts=1,
                      headers={"Authorization": f"Bearer {key}"})
    if not isinstance(data, dict):
        return None
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message") or {}
    out = _clean_output(message.get("content") or "")
    if not out or not _looks_translated(out, target):
        return None
    return out


def free_translate(text: str, *, target: str = TARGET_DEFAULT,
                   src: str = "en", timeout: float = 9.0) -> str | None:
    """免费免 Key 兜底接口（MyMemory）。失败返回 None。"""
    src = (src or "en").lower()
    if src not in ("en", "ja", "zh-cn", "zh-tw", "zh"):
        src = "en"
    langpair = f"{src}|{target}"
    url = (f"{FREE_ENDPOINT}?q={urllib.parse.quote(text)}"
           f"&langpair={urllib.parse.quote(langpair)}")
    data = fetch_json(url, timeout=timeout, attempts=2)
    if not isinstance(data, dict):
        return None
    status = data.get("responseStatus")
    if status not in (200, "200", None):
        return None
    payload = data.get("responseData") or {}
    out = _clean_output(payload.get("translatedText") or "")
    if not out or "MYMEMORY WARNING" in out.upper():
        return None
    if not _looks_translated(out, target):
        return None
    return out


# --------------------------------------------------------------------------- #
# 缓存 + provider 链
# --------------------------------------------------------------------------- #
def _cache_key(provider: str, model: str, target: str, text: str) -> str:
    return hashlib.sha1(f"{provider}|{model}|{target}|{text}".encode("utf-8")).hexdigest()


def _cached(provider: str, model: str, target: str, text: str, fn):
    key = _cache_key(provider, model, target, text)
    hit = cache_get("translate", key, TRANSLATE_TTL)
    if isinstance(hit, dict) and hit.get("text"):
        return hit["text"]
    out = fn()
    if out:
        cache_put("translate", key, {
            "text": out, "provider": provider, "model": model,
            "target": target, "at": int(time.time()),
        })
    return out


def translate_text(text: str, *, target: str = TARGET_DEFAULT,
                   settings: dict | None = None, plugin_translate=None) -> dict:
    """把简介翻译成目标语言。

    返回 {text, provider, changed, lang}：
    - text     最终文本（失败时就是原文）
    - provider 'llm' | 'free' | 'plugin:<id>' | 'none'
    - changed  是否真的翻译了
    - lang     原文语言（zh / ja / en / other / empty）

    `plugin_translate`：P6.4 起由服务层注入的插件引擎回调
    `fn(text, target=…) -> str|None`；只有 `translate_provider` 写成 `plugin:<id>` 时才会用到。
    显式选了插件就**不静默换引擎**（和「仅 LLM / 仅免费」同一套语义），失败时保持原文并附 `error`。
    """
    cfg = settings or {}
    raw = clean_html(text or "").strip()
    lang = detect_language(raw)
    result = {"text": raw, "provider": "none", "changed": False, "lang": lang}

    if not raw or not needs_translation(raw, target):
        return result
    if len(raw) > _MAX_INPUT:
        raw = _truncate(raw, _MAX_INPUT)

    mode = str(cfg.get("translate_provider") or "auto").lower()
    model = str(cfg.get("translate_model") or "deepseek-chat").strip()

    if mode.startswith("plugin:"):
        out = None
        if callable(plugin_translate):
            out = _cached(mode, model, target, raw,
                          lambda: plugin_translate(raw, target=target))
        if out:
            result.update(text=out, provider=mode, changed=True)
        else:
            result["provider"] = mode
            result["error"] = ("plugin-failed" if callable(plugin_translate)
                               else "plugin-unavailable")
        return result

    if mode in ("auto", "llm"):
        out = _cached("llm", model, target, raw,
                      lambda: llm_translate(raw, target=target, settings=cfg))
        if out:
            result.update(text=out, provider="llm", changed=True)
            return result
        if mode == "llm":
            return result

    if mode in ("auto", "free"):
        src = lang if lang in ("en", "ja") else "en"
        out = _cached("free", src, target, raw,
                      lambda: free_translate(raw, target=target, src=src))
        if out:
            result.update(text=out, provider="free", changed=True)
            return result

    return result


def test_provider(settings: dict | None = None, plugin_translate=None) -> dict:
    """设置面板的「测试」按钮：用一段样例文本实时验证接口是否可用（绕过缓存）。"""
    cfg = settings or {}
    sample = ("The story follows a young swordsman who must protect his hometown "
              "from an invading army.")
    mode = str(cfg.get("translate_provider") or "auto").lower()
    errors: list[str] = []

    if mode.startswith("plugin:"):
        name = mode.split(":", 1)[1].strip() or mode
        if not callable(plugin_translate):
            return {"ok": False, "provider": mode,
                    "error": f"插件 {name} 不可用（没加载或已被自动禁用）"}
        out = plugin_translate(sample, target=TARGET_DEFAULT)
        if out:
            return {"ok": True, "provider": mode, "text": out}
        return {"ok": False, "provider": mode, "error": f"插件 {name} 翻译失败"}

    if mode in ("auto", "llm"):
        if not str(cfg.get("translate_api_key") or "").strip():
            errors.append("未填写 API Key")
        else:
            out = llm_translate(sample, target=TARGET_DEFAULT, settings=cfg)
            if out:
                return {"ok": True, "provider": "llm", "text": out}
            errors.append("LLM 接口调用失败")
        if mode == "llm":
            return {"ok": False, "provider": "llm", "error": "；".join(errors)}

    if mode in ("auto", "free"):
        out = free_translate(sample, target=TARGET_DEFAULT, src="en")
        if out:
            return {"ok": True, "provider": "free", "text": out}
        errors.append("免费接口调用失败")

    return {"ok": False, "provider": mode, "error": "；".join(errors) or "翻译失败"}
