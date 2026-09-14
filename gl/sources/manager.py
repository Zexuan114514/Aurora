"""资料源管理器：注册、排序、搜索打分、拉取详情、跨源补图。"""
from __future__ import annotations

import time

from .. import config
from ..detect import score_candidate
from . import net
from .base import Candidate, Metadata, Source
from .bangumi import BangumiSource
from .custom import CustomApiSource, CustomLinkSource, from_config
from .steam import SteamSource
from .vndb import VNDBSource

BUILTIN: dict[str, type[Source]] = {
    "steam": SteamSource,
    "vndb": VNDBSource,
    "bangumi": BangumiSource,
}

DEFAULT_CONFIG = {
    "order": ["steam", "vndb", "bangumi"],
    "disabled": [],
    "merge_images": True,
    "custom": [],
}

# 非“本体”内容，命中时降权（除非查询词里本来就有）
SECONDARY_WORDS = (
    "soundtrack", "sound track", "ost", "dlc", "expansion", "season pass", "upgrade",
    "demo", "beta", "benchmark", "artbook", "art book", "wallpaper", "editor", "sdk",
    "mod kit", "creation kit", "tool", "bonus", "add-on", "addon", "extra pack",
    "digital deluxe", "premium bundle", "supporter pack", "starter pack", "fan disc",
)


def _secondary_penalty(name: str, queries: list[str]) -> float:
    lowered = (name or "").lower()
    if not lowered:
        return 1.0
    for word in SECONDARY_WORDS:
        if word in lowered and not any(word in (q or "").lower() for q in queries):
            return 0.85
    return 1.0


def _score(candidate: Candidate, queries: list[str],
           primary: list[str]) -> tuple[float, float, bool, bool]:
    """返回 (总分, 主关键词分, 是否命中主关键词, 是否归一化后完全一致)。"""
    from ..detect import norm

    names = candidate.names or [candidate.name]
    best = 0.0
    best_primary = 0.0
    best_index = 0
    exact = False
    penalty = 1.0
    for name in names:
        key = norm(name)
        for index, query in enumerate(queries):
            value = score_candidate([query], name)
            if value > best or (index == 0 and value == best and best_index != 0):
                best = value
                best_index = index
            if key and key == norm(query):
                exact = True
        best_primary = max(best_primary, score_candidate(primary, name))
        penalty = min(penalty, _secondary_penalty(name, queries))
    return (round(best * penalty, 4), round(best_primary * penalty, 4),
            best_index == 0, exact)


def _acceptable(score: float, primary: float, threshold: float, relaxed: bool,
                exact: bool = False) -> bool:
    """打分是否足以自动采纳。

    - 归一化后完全一致（exact）：直接接受
    - 主关键词高度匹配：接受
    - 只命中了备选关键词（例如目录名叫 sandbox）：要求总分达标且主关键词也有一定相似度，
      否则很容易误配到名字毫不相干的游戏
    """
    if exact or primary >= 0.93:
        return True
    if score >= 0.93 and relaxed:
        return True
    if score >= threshold and primary >= 0.35:
        return True
    return relaxed and score >= threshold


class SourceManager:
    """按用户配置组织资料源。"""

    def __init__(self, library) -> None:
        self.library = library
        #: 记住搜索时拿到的原始候选，拉详情时要用（例如 Bangumi 的 R18 条目）
        self._candidates: dict[tuple[str, str], Candidate] = {}

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #
    def config(self) -> dict:
        raw = self.library.settings.get("sources")
        cfg = {**DEFAULT_CONFIG, **(raw or {})}
        cfg["order"] = [s for s in cfg.get("order") or [] if s in BUILTIN]
        for key in BUILTIN:
            if key not in cfg["order"]:
                cfg["order"].append(key)
        cfg["disabled"] = [s for s in (cfg.get("disabled") or []) if s in BUILTIN]
        cfg["custom"] = list(cfg.get("custom") or [])
        return cfg

    def save_config(self, cfg: dict) -> dict:
        clean = {
            "order": [s for s in (cfg.get("order") or []) if s in BUILTIN],
            "disabled": [s for s in (cfg.get("disabled") or []) if s in BUILTIN],
            "merge_images": bool(cfg.get("merge_images", True)),
            "custom": list(cfg.get("custom") or []),
        }
        self.library.set_setting("sources", clean)
        return self.config()

    def add_custom(self, cfg: dict) -> dict:
        import uuid

        current = self.config()
        entry = dict(cfg or {})
        entry["id"] = entry.get("id") or f"custom:{uuid.uuid4().hex[:8]}"
        entry.setdefault("kind", "api")
        current["custom"] = [c for c in current["custom"] if c.get("id") != entry["id"]] + [entry]
        self.save_config(current)
        return entry

    def remove_custom(self, source_id: str) -> bool:
        current = self.config()
        before = len(current["custom"])
        current["custom"] = [c for c in current["custom"] if c.get("id") != source_id]
        self.save_config(current)
        return len(current["custom"]) != before

    def set_enabled(self, source_id: str, enabled: bool) -> dict:
        current = self.config()
        disabled = set(current["disabled"])
        if enabled:
            disabled.discard(source_id)
        else:
            disabled.add(source_id)
        current["disabled"] = sorted(disabled)
        self.save_config(current)
        return self.config()

    def move(self, source_id: str, delta: int) -> dict:
        current = self.config()
        order = current["order"]
        if source_id in order:
            index = order.index(source_id)
            target = max(0, min(len(order) - 1, index + delta))
            order.insert(target, order.pop(index))
        self.save_config(current)
        return self.config()

    # ------------------------------------------------------------------ #
    # 源实例
    # ------------------------------------------------------------------ #
    def _instantiate(self, source_id: str) -> Source | None:
        if source_id in BUILTIN:
            return BUILTIN[source_id]()
        for entry in self.config()["custom"]:
            if entry.get("id") == source_id:
                return from_config(entry)
        return None

    def sources(self, include_disabled: bool = False) -> list[Source]:
        cfg = self.config()
        out: list[Source] = []
        for source_id in cfg["order"]:
            if not include_disabled and source_id in cfg["disabled"]:
                continue
            src = self._instantiate(source_id)
            if src:
                out.append(src)
        for entry in cfg["custom"]:
            if not include_disabled and entry.get("id") in cfg["disabled"]:
                continue
            src = from_config(entry)
            if src:
                out.append(src)
        return out

    def get(self, source_id: str) -> Source | None:
        return self._instantiate(source_id)

    def describe(self) -> list[dict]:
        """给设置界面用的源列表。"""
        cfg = self.config()
        rows = []
        for source_id in cfg["order"]:
            src = self._instantiate(source_id)
            if not src:
                continue
            rows.append({
                "id": source_id, "name": src.name, "kind": src.kind,
                "builtin": True, "enabled": source_id not in cfg["disabled"],
                "homepage": src.homepage, "search_url": src.search_url,
                "status": src.status(),
            })
        for entry in cfg["custom"]:
            src = from_config(entry)
            if not src:
                continue
            rows.append({
                "id": src.id, "name": src.name, "kind": src.kind,
                "builtin": False, "enabled": src.id not in cfg["disabled"],
                "homepage": src.homepage, "search_url": src.search_url,
                "status": src.status(), "config": entry,
            })
        return rows

    def link_sources(self) -> list[dict]:
        """只返回“跳转搜索”型的源。"""
        return [row for row in self.describe() if row["kind"] == "link" and row["enabled"]]

    # ------------------------------------------------------------------ #
    # 搜索
    # ------------------------------------------------------------------ #
    def resolve(self, queries: list[str], threshold: float = 0.75,
                timeout: float = 9.0, budget: float = 45.0,
                max_queries: int = 2) -> dict:
        queries = [q for q in (queries or []) if q and str(q).strip()][:max_queries]
        if not queries:
            return {"ok": False, "reason": "no-query", "candidates": []}

        deadline = time.time() + budget
        primary = queries[:1]
        pool: list[tuple[Candidate, float, float, bool, bool]] = []
        errors = 0
        tried = 0
        used: list[str] = []

        for source in self.sources():
            if source.kind != "api":
                continue
            if time.time() > deadline:
                break
            failures_before = net.failures()
            try:
                found = source.search(queries, timeout) or []
            except Exception as exc:
                config.log(f"source {source.id} search failed: {exc}")
                found = []
                errors += 1
            if net.failures() > failures_before:
                # 源内部把请求失败吞成了「没结果」，这里补记一次
                errors += 1
            for candidate in found:
                self.remember(candidate)
            tried += 1
            for candidate in found:
                score, prim, relaxed, exact = _score(candidate, queries, primary)
                candidate.score = score
                pool.append((candidate, score, prim, relaxed, exact))
            if found and queries[0] not in used:
                used.append(queries[0])
            pool.sort(key=lambda row: (-row[1], -row[2]))
            if pool and _acceptable(pool[0][1], pool[0][2], threshold, pool[0][3], pool[0][4]):
                break

        if not pool:
            # 有源报错时「没找到」这个结论并不可靠，直接按网络问题提示
            return {"ok": False,
                    "reason": "network" if errors else "no-results",
                    "candidates": [], "query": queries[:1]}

        best, score, prim, relaxed, exact = pool[0]
        if not _acceptable(score, prim, threshold, relaxed, exact):
            return {"ok": False, "reason": "low-confidence",
                    "candidates": [c.to_public() for c, *_ in pool[:12]],
                    "query": used[:1] or queries[:1]}

        return {
            "ok": True,
            "source": best.source,
            "source_id": best.source_id,
            "name": best.name,
            "score": score,
            "candidates": [c.to_public() for c, *_ in pool[:12]],
            "query": used[:1] or queries[:1],
        }

    # ------------------------------------------------------------------ #
    # 详情
    # ------------------------------------------------------------------ #
    def remember(self, candidate: Candidate) -> Candidate:
        self._candidates[(candidate.source, str(candidate.source_id))] = candidate
        return candidate

    def recall(self, source_id: str, candidate_id: str) -> Candidate | None:
        return self._candidates.get((source_id, str(candidate_id)))

    def fetch_metadata(self, source_id: str, candidate_id: str, name: str = "",
                       lang: str = "schinese", timeout: float = 9.0) -> Metadata | None:
        source = self.get(source_id)
        if source is None or source.kind != "api":
            return None
        candidate = self.recall(source_id, candidate_id) or Candidate(
            source=source_id, source_id=str(candidate_id), name=name)
        if name and not candidate.name:
            candidate.name = name
        try:
            return source.fetch(candidate, lang=lang, timeout=timeout)
        except Exception as exc:
            config.log(f"source {source_id} fetch failed: {exc}")
            return None

    def _merge_from_others(self, main: Metadata, lang: str, timeout: float,
                           deadline: float) -> None:
        """用其它源补齐图片/封面（要求近乎精确匹配，避免张冠李戴）。"""
        names = [n for n in (main.name_cn, main.name_original, main.name) if n]
        if not names:
            return
        for source in self.sources():
            if source.kind != "api" or source.id == main.source:
                continue
            if time.time() > deadline:
                break
            try:
                found = source.search(names[:2], timeout) or []
            except Exception:
                continue
            best: Candidate | None = None
            best_score = 0.0
            for candidate in found:
                score, _, _, _ = _score(candidate, names, names[:1])
                if score > best_score:
                    best, best_score = candidate, score
            if best is None or best_score < 0.95:
                continue
            extra = self.fetch_metadata(source.id, best.source_id, best.name, lang, timeout)
            if extra:
                main.merge_images(extra)

    def build(self, source_id: str, candidate_id: str, name: str = "",
              lang: str = "schinese", timeout: float = 9.0,
              merge: bool | None = None, budget: float = 20.0) -> dict | None:
        """拉取详情并整理成入库用的字典。"""
        meta = self.fetch_metadata(source_id, candidate_id, name, lang, timeout)
        if meta is None:
            return None
        cfg = self.config()
        if merge is None:
            merge = bool(cfg.get("merge_images", True))
        if merge:
            self._merge_from_others(meta, lang, timeout, time.time() + budget)

        data = meta.to_public()
        images = data["images"]
        cover = data["cover"]
        if not cover and images:
            cover = images[0]["url"]
            data["cover"] = cover
        if cover and cover not in data["cover_sources"]:
            data["cover_sources"].insert(0, cover)
        if not data["cover_sources"] and images:
            data["cover_sources"] = [img["url"] for img in images[:3]]

        return {
            "source": meta.source,
            "source_id": str(meta.source_id),
            "source_url": meta.source_url,
            "appid": int(meta.source_id) if meta.source == "steam" and meta.source_id.isdigit()
            else None,
            "steam_name": meta.name,
            "name": meta.name,
            "name_cn": meta.name_cn,
            "name_original": meta.name_original,
            "description": meta.description,
            "about": meta.about,
            "developers": meta.developers,
            "publishers": meta.publishers,
            "genres": meta.genres,
            "categories": meta.categories,
            "release_date": meta.release_date,
            "rating": meta.rating,
            "metacritic": None,
            "website": meta.website,
            "store_url": meta.source_url,
            "cover": data["cover"],
            "cover_sources": data["cover_sources"],
            "logo": meta.logo,
            "header_image": meta.header_image,
            "images": images,
        }

    # ------------------------------------------------------------------ #
    def test(self, source_id: str, query: str = "千恋万花") -> dict:
        """在设置界面里测试一个源。"""
        source = self.get(source_id)
        if source is None:
            return {"ok": False, "error": "not-found"}
        if source.kind == "link":
            return {"ok": True, "kind": "link", "link": source.link_for(query)}
        started = time.time()
        try:
            found = source.search([query], 8.0) or []
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        elapsed = time.time() - started
        return {
            "ok": bool(found),
            "kind": "api",
            "elapsed": round(elapsed, 2),
            "count": len(found),
            "sample": [c.name for c in found[:3]],
        }
