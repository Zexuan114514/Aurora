"""插件翻译引擎适配（P6.4，ADR-0009）：把 `data/plugins/translators/<id>` 包成宿主引擎。

契约（`contracts/plugin-api-v1.md`）：插件写
`translate(text, *, context, target, glossary, on_delta)`，返回 `{"text": …, "provider": …}`。
宿主这边只做三件事：
  1. 归一化入参 / 返回值（dict、纯字符串都收；插件只给整段时补一段流式回执）
  2. 调用全部走 `CallGuard`（连续 3 次失败自动禁用，异常不外抛）
  3. 按 `plugin:<id>` 现查现建适配器（重新扫描插件后自动换成新实例，不留旧状态）

缓存不在这里做（契约写明「缓存归宿主」）：简介链路走 `gl.translate` 的缓存，
游戏内逐句链路走 `linetrans` 的缓存。
"""
from __future__ import annotations

from aurora.infra.plugins import CallGuard


class PluginTranslator:
    """一个 translator 插件 = 一个宿主翻译引擎（`status` 就是加载时那份）。"""

    def __init__(self, status, logger=None) -> None:
        self._status = status
        self._plugin = status.plugin
        self._guard = CallGuard(status, logger=logger)
        self.id = status.id
        self.name = status.name or status.id
        self.requires_key = bool(getattr(self._plugin, "requires_key", False))
        self.supports_stream = bool(getattr(self._plugin, "supports_stream", False))

    @property
    def provider(self) -> str:
        """写进设置 / 事件 / 历史里的引擎名（`plugin:<id>`）。"""
        return f"plugin:{self.id}"

    @property
    def plugin_status(self):
        return self._status

    def available(self) -> bool:
        return self._status.ok

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "provider": self.provider,
                "requires_key": self.requires_key, "supports_stream": self.supports_stream,
                "state": self._status.state, "detail": self._status.detail}

    def translate(self, text: str, *, context: list | None = None,
                  glossary: dict | None = None, target: str = "zh-CN",
                  on_delta=None) -> str | None:
        """调一次插件；失败或空结果返回 None（异常已进 CallGuard 计数，不再外抛）。"""
        if not self._status.ok:
            return None
        pieces: list[str] = []

        def _delta(piece) -> bool:
            piece = str(piece or "")
            if not piece:
                return True
            pieces.append(piece)
            if callable(on_delta):
                on_delta(piece)
            return True

        try:
            result = self._guard.call(
                self._plugin.translate, str(text),
                context=list(context or []), target=str(target or "zh-CN"),
                glossary=dict(glossary or {}), on_delta=_delta)
        except Exception:                                   # noqa: BLE001
            return None
        out = ""
        if isinstance(result, dict):
            out = str(result.get("text") or "").strip()
        elif result is not None:
            out = str(result).strip()
        if not out and pieces:
            out = "".join(pieces).strip()
        if out and not pieces and callable(on_delta):
            on_delta(out)        # 插件只给了整段：补一段，界面照样有流式回执
        return out or None


class TranslatorRegistry:
    """`plugin:<id>` → `PluginTranslator` 的取用口（`PluginsService` 背后的状态说了算）。"""

    def __init__(self, plugins_service, logger=None) -> None:
        self._service = plugins_service
        self._logger = logger
        self._adapters: dict[str, tuple[int, PluginTranslator]] = {}

    def _statuses(self) -> list:
        try:
            rows = self._service.statuses()
        except Exception:                                   # noqa: BLE001
            return []
        return [s for s in rows if getattr(s, "kind", "") == "translators"]

    def all(self) -> list[PluginTranslator]:
        rows = self._statuses()
        live = {s.id for s in rows}
        for gone in [pid for pid in self._adapters if pid not in live]:
            self._adapters.pop(gone, None)                  # 插件被删/改名后不留旧适配器
        out = []
        for status in rows:
            adapter = self._adapter_for(status)
            if adapter is not None:
                out.append(adapter)
        return out

    def get(self, plugin_id: str) -> PluginTranslator | None:
        if not plugin_id:
            return None
        for status in self._statuses():
            if status.id == plugin_id and status.ok:
                return self._adapter_for(status)
        return None

    def from_provider(self, provider: str) -> PluginTranslator | None:
        """`plugin:<id>` → 适配器；`auto` / `llm` / `free` 这类返回 None。"""
        text = str(provider or "")
        if not text.startswith("plugin:"):
            return None
        return self.get(text.split(":", 1)[1].strip())

    def _adapter_for(self, status) -> PluginTranslator | None:
        """同一个 status 复用同一个适配器（保住 CallGuard 的失败计数）。"""
        if not status.ok:
            return None
        cached = self._adapters.get(status.id)
        if cached and cached[0] == id(status):
            return cached[1]
        adapter = PluginTranslator(status, logger=self._logger)
        self._adapters[status.id] = (id(status), adapter)
        return adapter
