"""Bangumi 番组计划资料源（api.bgm.tv，公开只读接口，无需 token）。

中文资料最全，能拿到中文名、中文简介和封面，适合补足 VNDB 缺中文简介的问题。
Bangumi 要求请求带上能识别应用的 User-Agent。
"""
from __future__ import annotations

from . import net
from .base import Candidate, Metadata, Source

SEARCH_API = "https://api.bgm.tv/v0/search/subjects"
LEGACY_SEARCH = "https://api.bgm.tv/search/subject/"
SUBJECT_API = "https://api.bgm.tv/v0/subjects/"
SEARCH_TTL = 7 * 24 * 3600
DETAIL_TTL = 30 * 24 * 3600

#: 4 = 游戏
SUBJECT_TYPE_GAME = 4
UA = "AuroraGameLauncher/1.0 (https://github.com/aurora-launcher; personal game library tool)"

_DEV_KEYS = ("开发", "开发商", "游戏开发商", "ブランド", "开发团队")
_PUB_KEYS = ("发行", "发行商", "出版社", "販売")
_PLATFORM_KEYS = ("平台", "游戏平台", "プラットフォーム")


def _https(url: str) -> str:
    """旧接口返回 http 图片地址，WebView2 里会被当成混合内容拦掉。"""
    url = (url or "").strip()
    return "https://" + url[7:] if url.startswith("http://") else url


def _infobox_value(infobox: list[dict], keys: tuple[str, ...]) -> list[str]:
    """从 infobox 里按 key 取值（值可能是字符串或 [{v: ...}] 列表）。"""
    out: list[str] = []
    for item in infobox or []:
        if (item.get("key") or "") not in keys:
            continue
        value = item.get("value")
        if isinstance(value, list):
            for row in value:
                text = (row.get("v") if isinstance(row, dict) else str(row)) or ""
                text = text.strip()
                if text and text not in out:
                    out.append(text)
        elif isinstance(value, str) and value.strip():
            if value.strip() not in out:
                out.append(value.strip())
    return out


class BangumiSource(Source):
    id = "bangumi"
    name = "Bangumi 番组计划"
    kind = "api"
    homepage = "https://bgm.tv/"
    search_url = "https://bgm.tv/subject_search/{query}?cat=4"
    supports_lang = True

    def _search_once(self, query: str, timeout: float) -> list[dict] | None:
        """先试旧版搜索接口（对中文/日文关键词命中率明显更高），再退回 v0。"""
        key = f"search|{query}"
        cached = net.cache_get("bangumi", key, SEARCH_TTL)
        if cached is not None:
            return cached.get("rows", [])

        url = LEGACY_SEARCH + net.quote(query) + "?type=4&responseGroup=small"
        payload = net.fetch_json(url, timeout=timeout, ua=UA, attempts=1,
                                 headers={"User-Agent": UA})
        rows: list[dict] = []
        if isinstance(payload, dict) and payload.get("list"):
            rows = [row for row in payload["list"] if row.get("type") == SUBJECT_TYPE_GAME]
        if not rows:
            payload = net.fetch_json(
                SEARCH_API, method="POST", timeout=timeout, ua=UA, attempts=1,
                headers={"User-Agent": UA},
                body={"keyword": query, "filter": {"type": [SUBJECT_TYPE_GAME]}, "limit": 10})
            if payload is None and not rows:
                return None
            rows = (payload or {}).get("data") or []
        net.cache_put("bangumi", key, {"rows": rows})
        return rows

    def search(self, queries: list[str], timeout: float = 9.0) -> list[Candidate]:
        pool: dict[int, dict] = {}
        for query in queries[:2]:
            for row in self._search_once(query, timeout) or []:
                if row.get("id"):
                    pool.setdefault(int(row["id"]), row)

        out = []
        for row in pool.values():
            images = row.get("images") or {}
            cover = _https(images.get("large") or images.get("common") or "")
            names = [n for n in (row.get("name_cn"), row.get("name")) if n]
            out.append(Candidate(
                source=self.id,
                source_id=str(row["id"]),
                name=row.get("name_cn") or row.get("name") or "",
                names=names,
                cover=cover,
                thumb=_https(images.get("common") or cover),
                extra={"id": row["id"]},
            ))
        return out

    def fetch(self, candidate: Candidate, lang: str = "schinese",
              timeout: float = 9.0) -> Metadata | None:
        sid = str(candidate.source_id)
        key = f"detail|{sid}"
        missing_key = f"missing|{sid}"
        cached = net.cache_get("bangumi", key, DETAIL_TTL)
        if cached is not None:
            row = cached.get("row") or {}
        elif net.cache_get("bangumi", missing_key, DETAIL_TTL) is not None:
            # 已知接口查不到（R18 等受限条目），不再反复请求（否则日志会被 404 刷屏）
            row = candidate.extra.get("row") or {}
        else:
            payload = net.fetch_json(SUBJECT_API + sid, timeout=timeout, ua=UA,
                                     headers={"User-Agent": UA})
            row = payload if isinstance(payload, dict) and payload.get("id") else {}
            # R18 / 受限条目在 v0 接口会返回 404，退回搜索结果里已有的信息
            if not row:
                row = candidate.extra.get("row") or {}
            if not row and candidate.name:
                # 手工选择或重启后 extra 丢了，就按名字再搜一次
                for item in self._search_once(candidate.name, timeout) or []:
                    if str(item.get("id")) == sid:
                        row = item
                        break
            if row:
                net.cache_put("bangumi", key, {"row": row})
            else:
                net.cache_put("bangumi", missing_key, {"restricted": True})
        if not row:
            # 连搜索结果都拿不到时，至少把名字和封面用上
            if not candidate.name and not candidate.cover:
                return None
            return Metadata(
                source=self.id, source_id=sid,
                source_url=f"https://bgm.tv/subject/{sid}",
                name=candidate.name, name_cn=candidate.name,
                cover=candidate.cover,
                cover_sources=[candidate.cover] if candidate.cover else [],
                images=[{"url": candidate.cover, "kind": "cover", "label": "Bangumi 封面",
                         "thumb": candidate.cover}] if candidate.cover else [],
            )

        images = row.get("images") or {}
        cover = _https(images.get("large") or images.get("common") or "")
        infobox = row.get("infobox") or []
        tags = [t.get("name") for t in (row.get("tags") or []) if t.get("name")][:6]
        rating = (row.get("rating") or {}).get("score")

        summary = row.get("summary") or ""
        name_cn = row.get("name_cn") or ""
        name_original = row.get("name") or ""

        return Metadata(
            source=self.id,
            source_id=sid,
            source_url=f"https://bgm.tv/subject/{sid}",
            name=name_cn or name_original or candidate.name,
            name_cn=name_cn,
            name_original=name_original,
            description=summary[:400],
            about=summary[:6000],
            developers=_infobox_value(infobox, _DEV_KEYS),
            publishers=_infobox_value(infobox, _PUB_KEYS),
            genres=tags,
            release_date=row.get("date") or "",
            rating=(f"Bangumi {rating}" if rating else ""),
            cover=cover,
            cover_sources=[u for u in (_https(images.get("large")), _https(images.get("common")),
                                       _https(images.get("medium")), _https(images.get("small")))
                           if u],
            images=[{"url": cover, "kind": "cover", "label": "Bangumi 封面", "thumb": cover}]
            if cover else [],
            website=row.get("site") or "",
        )
