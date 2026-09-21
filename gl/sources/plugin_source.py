"""插件资料源适配（P6.3，ADR-0009）：把 `data/plugins/sources/<id>` 包装成宿主 Source。

插件按契约写 `search(query, lang)` / `fetch(candidate, lang)`；宿主这边是
`search(queries, timeout)` / `fetch(candidate, lang, timeout)`。差异都在这个适配器里抹平，
并把插件异常收进 `CallGuard`（连续 3 次失败自动禁用）。
"""
from __future__ import annotations

from aurora.domain.contracts import Candidate, Metadata
from aurora.infra.plugins import CallGuard
from .base import Source


class PluginSource(Source):
    """一个插件 = 一个资料源（`status` 就是加载时那份 `PluginStatus`）。"""

    def __init__(self, status, logger=None) -> None:
        self._status = status
        self._plugin = status.plugin
        self._guard = CallGuard(status, logger=logger)
        self.id = status.id
        self.name = status.name or status.id
        self.kind = str(getattr(self._plugin, "kind", "api") or "api")
        self.homepage = str(getattr(self._plugin, "homepage", "") or "")
        self.search_url = str(getattr(self._plugin, "search_url", "") or "")
        self.supports_lang = bool(getattr(self._plugin, "supports_lang", False))

    @property
    def plugin_status(self):
        return self._status

    def available(self) -> bool:
        return self._status.ok

    def status(self) -> str:
        return self._status.detail or ("可用" if self.available() else "不可用")

    # ------------------------------------------------------------------ #
    def search(self, queries: list[str], timeout: float = 9.0) -> list[Candidate]:
        """宿主给的是一串候选关键词；逐个问插件（第一个有结果就够，最多问三个）。"""
        out: list[Candidate] = []
        seen: set[str] = set()
        for query in list(queries or [])[:3]:
            rows = self._guard.call(self._plugin.search, str(query), "schinese") or []
            for row in rows:
                item = _as_candidate(row, self.id)
                if item is None or item.source_id in seen:
                    continue
                seen.add(item.source_id)
                out.append(item)
            if out:
                break
        return out

    def fetch(self, candidate: Candidate, lang: str = "schinese",
              timeout: float = 9.0) -> Metadata | None:
        data = self._guard.call(self._plugin.fetch, candidate, lang)
        return _as_metadata(data, candidate, self.id)


def _as_candidate(row, plugin_id: str) -> Candidate | None:
    if isinstance(row, Candidate):
        return row
    if not isinstance(row, dict) or not row.get("source_id"):
        return None
    return Candidate(
        source=str(row.get("source") or plugin_id),
        source_id=str(row["source_id"]),
        name=str(row.get("name") or row["source_id"]),
        names=[str(x) for x in (row.get("names") or [])],
        score=float(row.get("score") or 0.0),
        thumb=str(row.get("thumb") or ""),
        cover=str(row.get("cover") or ""),
        extra=dict(row.get("extra") or {}),
    )


def _as_metadata(data, candidate: Candidate, plugin_id: str) -> Metadata | None:
    if data is None:
        return None
    if isinstance(data, Metadata):
        return data
    if not isinstance(data, dict):
        return None
    allowed = {f for f in Metadata.__dataclass_fields__}          # noqa: SLF001
    fields = {k: v for k, v in data.items() if k in allowed}
    fields.setdefault("source", candidate.source or plugin_id)
    fields.setdefault("source_id", str(candidate.source_id))
    fields.setdefault("name", candidate.name)
    return Metadata(**fields)
