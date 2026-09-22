"""逐句翻译队列（P3.9 从 gl/linetrans.py 搬入）：缓存 / 上下文 / 术语表 / 流式回调。

事件向默认总线发布（engine.translate），由 Api 订阅后推给前端。
"""
from __future__ import annotations

from aurora.app.events import default_bus

from aurora.infra.tasks import default_runner

import hashlib
import json
import threading
import time
from pathlib import Path

from gl import config, netproxy

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
    """串行 + 可打断的逐句翻译器。

    P6.4：`plugin_getter` 注入「`plugin:<id>` → 插件翻译引擎」的取用口；设置里选了插件引擎时
    先走插件（带上下文 / 术语表 / 流式回调），插件没给出结果再落到原有的 LLM → 免费兜底链。
    """

    def __init__(self, *, settings_getter, on_event, plugin_getter=None) -> None:
        self._get_settings = settings_getter
        self._on_event = on_event              # (kind, payload) -> None
        self._get_plugin = plugin_getter       # (plugin_id) -> 适配器 | None（P6.4）
        self._lock = threading.RLock()
        self._history: list[dict] = []
        self._context: list[str] = []
        self._pending: list[dict] = []         # 待翻队列（旧 → 新）
        self._token = 0
        #: 同时跑几个翻译请求。**不能只有 1 个**：实测 LLM 单句 40~60 秒，单 worker 时
        #: 「翻页 → 开始翻译」要等上一句翻译完（用户反馈的「明显间隔」，引擎级钩子的游戏
        #: 尤其明显，因为它们出文更快、翻页更密）。两个 worker 让新句子立刻开始，
        #: 队列仍然保留语义（不掐断在飞请求，避免「一句有一句没有」）。
        self._workers: list[threading.Thread] = []
        self._paused = False
        self._streaming = True
        #: 「这条行已经有补完版了」的发射 id（见 submit 的 revise_of）：
        #: 缺字版的译文要是后到，不能再往历史/悬浮窗上顶一条残缺句
        self._replaced: dict[int, float] = {}

    # ------------------------------------------------------------------ #
    def submit(self, text: str, *, game_id: str = "", source: str = "hook",
               line_id: int = 0, revise_of: int = 0) -> None:
        """入队一句。`line_id` = 这条行的发射序号；`revise_of` = 它是某条行的补完版。

        `revise_of` 是**同一句的新版本**（缺字补全的完整版，见 vntext 的
        `_resolve_completions`）：译文算完原位替换历史里的缺字版，不新增一条，
        面板上不会出现「残句 + 完整句」两条。
        """
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
                                  "line_id": int(line_id or 0),
                                  "revise_of": int(revise_of or 0),
                                  "token": self._token, "at": time.time()})
            del self._pending[:-self.MAX_QUEUE]
            self._workers = [row for row in self._workers if row.is_alive()]
            while len(self._workers) < self.MAX_WORKERS:
                self._workers.append(
                    default_runner().spawn("linetrans.queue", self._loop,
                                           thread_name="aurora-linetrans"))
        self._fire("queued", {"text": text, "source": source})

    def retranslate_last(self) -> dict:
        with self._lock:
            last = self._history[-1] if self._history else None
        if not last:
            return {"ok": False, "error": "no-history"}
        self.submit(last["text"], game_id=last.get("game_id", ""), source="manual")
        return {"ok": True, "text": last["text"]}

    MAX_QUEUE = 4
    #: 并发翻译请求数（见 `_workers` 的说明）
    MAX_WORKERS = 2

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
    def _fire(self, kind: str, payload: dict, *, silent: bool = False) -> None:
        """`silent=True` = 这句是**旧台词**的补完版，只更新面板、别顶悬浮窗。"""
        try:
            if silent:
                payload = {**payload, "silent": True}
            if self._on_event:
                self._on_event(kind, payload)
            else:      # P3.7：没有回调时走事件总线（Api 用订阅接）
                default_bus().publish("engine.translate", {"kind": kind, **payload})
        except Exception as exc:
            config.log(f"linetrans callback failed: {exc}")

    def _entry_index(self, line_id: int) -> int:
        """历史里这条发射 id 的位置（从最新往前找；-1 = 没有）。调用方持锁。"""
        if not line_id:
            return -1
        for index in range(len(self._history) - 1, -1, -1):
            if int(self._history[index].get("id") or 0) == int(line_id):
                return index
        return -1

    def _revision_is_stale(self, revise_of: int) -> bool:
        """要补发的那句还是不是「当前这句」：已经不是了就别再顶悬浮窗。调用方持锁。"""
        if not revise_of:
            return False
        pos = self._entry_index(revise_of)
        return pos >= 0 and pos != len(self._history) - 1

    def _remember_replaced(self, line_id: int) -> None:
        """记下「这条行已经有补完版了」（缺字版译文后到就直接丢）。调用方持锁。"""
        if not line_id:
            return
        self._replaced[int(line_id)] = time.time()
        while len(self._replaced) > 128:
            self._replaced.pop(next(iter(self._replaced)))

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
                self._fire("error", {"text": job["text"], "error": str(exc)})

    def _run(self, job: dict) -> None:
        cfg = self._get_settings() or {}
        text = job["text"]
        target = str(cfg.get("translate_target") or "zh-CN")
        terms = glossary_terms(job.get("game_id", ""))
        context_lines = max(0, min(12, int(cfg.get("vntext_context_lines") or 4)))
        line_id = int(job.get("line_id") or 0)
        revise_of = int(job.get("revise_of") or 0)
        with self._lock:
            if line_id and not revise_of and line_id in self._replaced:
                # 这条缺字版的补完版已经出过译文了：这句来晚了，别再翻一遍
                config.log(f"linetrans dropped (已被补完版替换) {text[:22]!r}")
                return
            silent = self._revision_is_stale(revise_of)
            context = list(self._context[-context_lines:]) if context_lines else []

        cached = self._cache_get(text, cfg, terms, target)
        if cached:
            self._finish(job, cached, provider="cache", silent=silent)
            return

        self._fire("start", {"text": text, "source": job.get("source", "")},
                   silent=silent)
        collected: list[str] = []

        def on_delta(chunk: str) -> bool:
            # 排队之后不再「有新台词就掐掉这句」：掐掉就永远没有译文了
            # （实测表现为「一句有一句没有」）。流式内容照常吐，前端按原文对上号。
            collected.append(chunk)
            self._fire("delta", {"text": text, "delta": chunk,
                                 "so_far": "".join(collected)}, silent=silent)
            return True

        out = ""
        provider = "llm"
        fallback_from = ""
        engine = self._plugin_engine(cfg)
        if engine is not None:
            # 插件是用户显式选的引擎：先问它；它失败/没结果时仍走下面的宿主兜底链，
            # 保证「插件坏了也有译文」（失败已由 CallGuard 计数，三连失败自动禁用）。
            provider = engine.provider
            out = engine.translate(text, context=context, glossary=terms,
                                   target=target, on_delta=on_delta) or ""
            if not out:
                fallback_from = provider      # 记下兜底来源：界面要能看出这句不是插件给的
                provider = "llm"
        if not out:
            key = str(cfg.get("translate_api_key") or "").strip()
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
            self._fire("error", {"text": text, "error": "translate-failed"}, silent=silent)
            return
        self._cache_put(text, cfg, terms, target, out)
        self._finish(job, out, provider=provider, fallback_from=fallback_from,
                     silent=silent)

    def _plugin_engine(self, cfg: dict):
        """按 `translate_provider = plugin:<id>` 取插件引擎；没配/拿不到返回 None。"""
        getter = self._get_plugin
        if not callable(getter):
            return None
        mode = str(cfg.get("translate_provider") or "").lower()
        if not mode.startswith("plugin:"):
            return None
        try:
            return getter(mode.split(":", 1)[1].strip())
        except Exception as exc:                            # noqa: BLE001
            config.log(f"linetrans plugin lookup failed: {exc}")
            return None

    def _finish(self, job: dict, out: str, provider: str, fallback_from: str = "",
                *, silent: bool = False) -> None:
        text = job["text"]
        # 留一行耗时：排错时要量「翻页 → 看到译文」到底卡在排队还是请求
        waited = time.time() - float(job.get("at") or time.time())
        config.log(f"linetrans done [{provider}] {text[:22]!r} ({waited:.1f}s)")
        line_id = int(job.get("line_id") or 0)
        revise_of = int(job.get("revise_of") or 0)
        with self._lock:
            if line_id and not revise_of and line_id in self._replaced:
                # 缺字版的译文来晚了：它的补完版已经在历史里，别再补一条顶回面板
                config.log(f"linetrans dropped (已被补完版替换) {text[:22]!r}")
                return
            self._context.append(text)
            del self._context[:-12]
            entry = {"text": text, "translation": out,
                     "provider": provider, "source": job.get("source", ""),
                     "fallback_from": fallback_from,
                     "game_id": job.get("game_id", ""),
                     "at": int(time.time()), "id": line_id}
            pos = self._entry_index(revise_of)
            if pos >= 0:
                # 同一句的新版本（缺字补全的完整版）→ 原位替换，不新增一条
                entry["id"] = revise_of
                entry["revised"] = True
                self._history[pos] = entry
            else:
                self._history.append(entry)
                del self._history[:-MAX_HISTORY]
            # 无论有没有找到原条目（缺字版的译文可能还在排队），都记一笔：
            # 那条缺字版本身已经不需要再顶上来了
            self._remember_replaced(revise_of)
        # 每条都要发出去：排队后「过期」只意味着它比最新台词旧，不代表不用给译文
        self._fire("done", {"text": text, "translation": out, "provider": provider,
                            "fallback_from": fallback_from,
                            "source": job.get("source", ""),
                            "id": line_id, "revise_of": revise_of}, silent=silent)

    def _fallback(self, text: str, cfg: dict, target: str) -> str | None:
        from gl import translate

        if str(cfg.get("translate_api_key") or "").strip():
            return translate.llm_translate(text, target=target, settings=cfg)
        return translate.free_translate(text, target=target,
                                        src=translate.detect_language(text) or "ja")

    # ------------------------------------------------------------------ #
    def _cache_key(self, text: str, cfg: dict, terms: dict, target: str) -> str:
        mode = str(cfg.get("translate_provider") or "")
        payload = json.dumps({
            "text": text,
            "model": cfg.get("translate_model") or "",
            # P6.4：插件引擎单独分段，避免换引擎后吃到别的引擎的旧译文；
            # 非插件模式不参与，老缓存键保持不变
            "engine": mode if mode.startswith("plugin:") else "",
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
