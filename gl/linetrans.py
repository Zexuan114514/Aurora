"""逐句翻译管线：把游戏里抓到的日文送进 LLM，流式吐回中文。

- 上下文：默认把前面几句一起送给模型，人称与语气更连贯
- 术语表：data/glossary.json（全局 + 每游戏），命中术语作为硬约束写进提示词
- 同一时刻只保留一个在飞请求，新台词来了就丢弃旧请求的后续推送
- 结果按「原文 + 模型 + 目标语言 + 术语表版本」缓存，重复台词秒出
"""
from __future__ import annotations

from aurora.app.events import default_bus

from aurora.infra.tasks import default_runner

import hashlib
import json
import threading
import time
from pathlib import Path

from . import config, netproxy

MAX_HISTORY = 200

SYSTEM_PROMPT = (
    "你是资深的视觉小说本地化译者。把用户给你的日文台词翻译成简体中文，要求：\n"
    "1. 只输出译文本身，不要解释、不要加引号、不要罗马字注音；\n"
    "2. 保持角色语气（敬语/口语/方言按原意体现），保留人名与专有名词的既有译法；\n"
    "3. 遇到拟声词、省略号、「——」这类写法按中文习惯自然处理；\n"
    "4. 若同时给了「上文」，只用它来理解人称与语境，不要翻译上文。"
)


def _glossary_path() -> Path:
    """术语表路径：v2 在 vntext/glossary.json；v1 的 data/glossary.json 仍可读（未迁移时）。"""
    target = config.GLOSSARY_FILE
    if not target.exists() and config.LEGACY_GLOSSARY_FILE.exists():
        return config.LEGACY_GLOSSARY_FILE
    return target


def load_glossary() -> dict:
    raw = config.read_json(_glossary_path(), {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("global", {})
    raw.setdefault("games", {})
    raw.setdefault("version", 1)
    return raw


def save_glossary(data: dict) -> None:
    config.write_json(_glossary_path(), data)


def glossary_terms(game_id: str = "") -> dict:
    data = load_glossary()
    terms = dict(data.get("global") or {})
    if game_id:
        terms.update((data.get("games") or {}).get(game_id) or {})
    return terms


class LineTranslator:
    """串行 + 可打断的逐句翻译器。"""

    def __init__(self, *, settings_getter, on_event) -> None:
        self._get_settings = settings_getter
        self._on_event = on_event              # (kind, payload) -> None
        self._lock = threading.RLock()
        self._history: list[dict] = []
        self._context: list[str] = []
        self._pending: list[dict] = []         # 待翻队列（旧 → 新）
        self._token = 0
        self._worker: threading.Thread | None = None
        self._paused = False
        self._streaming = True

    # ------------------------------------------------------------------ #
    def submit(self, text: str, *, game_id: str = "", source: str = "hook") -> None:
        text = (text or "").strip()
        if not text:
            return
        if self._paused:
            return
        with self._lock:
            self._token += 1
            # 排队而不是「新的顶掉旧的」：实测快速翻页时旧请求会被掐断，那一句就
            # 永远没有译文（表现为「一句有一句没有」）。队列只留最近几条，
            # 保证每句都翻到、同时不会越堆越久。
            self._pending.append({"text": text, "game_id": game_id, "source": source,
                                  "token": self._token})
            del self._pending[:-self.MAX_QUEUE]
            if self._worker is None or not self._worker.is_alive():
                self._worker = default_runner().spawn("linetrans.queue", self._loop,
                                                      thread_name="aurora-linetrans")
        self._emit("queued", {"text": text, "source": source})

    def retranslate_last(self) -> dict:
        with self._lock:
            last = self._history[-1] if self._history else None
        if not last:
            return {"ok": False, "error": "no-history"}
        self.submit(last["text"], game_id=last.get("game_id", ""), source="manual")
        return {"ok": True, "text": last["text"]}

    MAX_QUEUE = 4

    def set_paused(self, paused: bool) -> dict:
        with self._lock:
            self._paused = bool(paused)
        return {"ok": True, "paused": self._paused}

    def paused(self) -> bool:
        return self._paused

    def clear_context(self) -> dict:
        with self._lock:
            self._context.clear()
        return {"ok": True}

    def history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._history[-limit:])

    # ------------------------------------------------------------------ #
    def _emit(self, kind: str, payload: dict) -> None:
        try:
            if self._on_event:
                self._on_event(kind, payload)
            else:      # P3.7：没有回调时走事件总线（Api 用订阅接）
                default_bus().publish("engine.translate", {"kind": kind, **payload})
        except Exception as exc:
            config.log(f"linetrans callback failed: {exc}")

    def _loop(self) -> None:
        while True:
            with self._lock:
                job = self._pending.pop(0) if self._pending else None
                resume = not self._paused
            if job is None:
                return
            if not resume:
                continue
            try:
                self._run(job)
            except Exception as exc:
                config.log(f"linetrans run failed: {exc}")
                self._emit("error", {"text": job["text"], "error": str(exc)})

    def _run(self, job: dict) -> None:
        cfg = self._get_settings() or {}
        text = job["text"]
        target = str(cfg.get("translate_target") or "zh-CN")
        terms = glossary_terms(job.get("game_id", ""))
        context_lines = max(0, min(12, int(cfg.get("vntext_context_lines") or 4)))
        with self._lock:
            context = list(self._context[-context_lines:]) if context_lines else []

        cached = self._cache_get(text, cfg, terms, target)
        if cached:
            self._finish(job, cached, provider="cache")
            return

        self._emit("start", {"text": text, "source": job.get("source", "")})
        collected: list[str] = []

        def on_delta(chunk: str) -> bool:
            # 排队之后不再「有新台词就掐掉这句」：掐掉就永远没有译文了
            # （实测表现为「一句有一句没有」）。流式内容照常吐，前端按原文对上号。
            collected.append(chunk)
            self._emit("delta", {"text": text, "delta": chunk,
                                 "so_far": "".join(collected)})
            return True

        out = ""
        key = str(cfg.get("translate_api_key") or "").strip()
        provider = "llm"
        if key and self._streaming:
            try:
                out = stream_llm(text, cfg, context=context, glossary=terms,
                                 on_delta=on_delta) or ""
            except Exception as exc:
                config.log(f"linetrans stream failed: {exc}")
                out = ""
        if not out:
            provider = "llm" if key else "free"
            out = self._fallback(text, cfg, target) or ""
        if not out:
            self._emit("error", {"text": text, "error": "translate-failed"})
            return
        self._cache_put(text, cfg, terms, target, out)
        self._finish(job, out, provider=provider)

    def _finish(self, job: dict, out: str, provider: str) -> None:
        text = job["text"]
        with self._lock:
            self._context.append(text)
            del self._context[:-12]
            self._history.append({"text": text, "translation": out,
                                  "provider": provider, "source": job.get("source", ""),
                                  "game_id": job.get("game_id", ""),
                                  "at": int(time.time())})
            del self._history[:-MAX_HISTORY]
        # 每条都要发出去：排队后「过期」只意味着它比最新台词旧，不代表不用给译文
        self._emit("done", {"text": text, "translation": out, "provider": provider,
                            "source": job.get("source", "")})

    def _fallback(self, text: str, cfg: dict, target: str) -> str | None:
        from . import translate

        if str(cfg.get("translate_api_key") or "").strip():
            return translate.llm_translate(text, target=target, settings=cfg)
        return translate.free_translate(text, target=target,
                                        src=translate.detect_language(text) or "ja")

    # ------------------------------------------------------------------ #
    def _cache_key(self, text: str, cfg: dict, terms: dict, target: str) -> str:
        payload = json.dumps({
            "text": text,
            "model": cfg.get("translate_model") or "",
            "target": target,
            "glossary": sorted(terms.items()),
        }, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _cache_file(self, key: str) -> Path:
        folder = config.CACHE_DIR / "vntext"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{key}.json"

    def _cache_get(self, text: str, cfg: dict, terms: dict, target: str) -> str:
        try:
            path = self._cache_file(self._cache_key(text, cfg, terms, target))
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                return str(data.get("translation") or "")
        except Exception:
            pass
        return ""

    def _cache_put(self, text: str, cfg: dict, terms: dict, target: str, out: str) -> None:
        try:
            path = self._cache_file(self._cache_key(text, cfg, terms, target))
            path.write_text(json.dumps({"text": text, "translation": out},
                                       ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            config.log(f"linetrans cache write failed: {exc}")


# --------------------------------------------------------------------------- #
def build_messages(text: str, *, context: list[str] | None = None,
                   glossary: dict | None = None, target: str = "zh-CN") -> list[dict]:
    lines = []
    if glossary:
        pairs = "；".join(f"{src} → {dst}" for src, dst in list(glossary.items())[:40])
        lines.append(f"术语表（必须遵守）：{pairs}")
    if context:
        lines.append("上文（只用于理解语境，不要翻译）：\n" + "\n".join(context[-8:]))
    lines.append(f"目标语言：{target}\n请翻译下面这句日文台词：")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(lines) + "\n" + text},
    ]


def stream_llm(text: str, cfg: dict, *, context: list[str] | None = None,
               glossary: dict | None = None, target: str = "zh-CN",
               on_delta=None, timeout: float = 60.0) -> str:
    """OpenAI 兼容接口的流式调用；on_delta 返回 False 表示调用方已不需要这条。"""
    import urllib.request

    key = str(cfg.get("translate_api_key") or "").strip()
    base = str(cfg.get("translate_base_url") or "https://api.deepseek.com").strip().rstrip("/")
    if not key or not base:
        return ""
    model = str(cfg.get("translate_model") or "deepseek-chat").strip() or "deepseek-chat"
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "stream": True,
        "messages": build_messages(text, context=context, glossary=glossary,
                                   target=target),
    }).encode("utf-8")
    request = urllib.request.Request(
        url, method="POST", data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "Accept": "text/event-stream",
            "User-Agent": config.USER_AGENT,
        })
    route = netproxy.current()
    opener = netproxy.build_opener(route.get("proxy") or "")
    collected: list[str] = []
    with opener.open(request, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line or not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                payload = json.loads(chunk)
            except Exception:
                continue
            choices = payload.get("choices") or []
            if not choices:
                continue
            delta = (choices[0].get("delta") or {}).get("content")
            if not delta:
                continue
            collected.append(delta)
            if on_delta and on_delta(delta) is False:
                break
    return "".join(collected).strip()
