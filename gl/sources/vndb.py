"""VNDB 资料源（api.vndb.org/kana，公开只读接口，无需 token）。

VNDB 是 galgame / 视觉小说的权威数据库，返回原文名 + 中文名 + 英文名，
以及封面和多张截图，非常适合 Steam 上没有的作品。
"""
from __future__ import annotations

from . import net
from .base import Candidate, Metadata, Source

API = "https://api.vndb.org/kana/vn"
SEARCH_TTL = 7 * 24 * 3600
DETAIL_TTL = 30 * 24 * 3600

SEARCH_FIELDS = "id,title,alttitle,image.url,titles{lang,title,official},released,developers{name}"
DETAIL_FIELDS = ("id,title,alttitle,image.url,titles{lang,title,official},description,"
                 "released,developers{name},developers{name},tags{name,rating},"
                 "screenshots{url,thumbnail,sexual,violence},length_minutes,rating,"
                 "developers{name}")

_LANG_PRIORITY = ("zh-Hans", "zh-Hant", "zh", "en", "ja")


def _is_chinese(lang: str) -> bool:
    lang = (lang or "").lower()
    return lang.startswith(("zh", "schinese", "chinese", "cht", "chs"))


def _pick_title(titles: list[dict], lang: str) -> str:
    """按语言优先级取一个标题。"""
    if not titles:
        return ""
    by_lang: dict[str, list[str]] = {}
    for row in titles:
        key = (row.get("lang") or "").lower()
        title = (row.get("title") or "").strip()
        if title:
            by_lang.setdefault(key, []).append(title)

    if _is_chinese(lang):
        order = ("zh-hans", "zh-hant", "zh", "ja", "en")
    elif (lang or "").lower().startswith(("ja", "jp")):
        order = ("ja", "zh-hans", "zh-hant", "en")
    else:
        order = ("en", "ja", "zh-hans", "zh-hant")
    for key in order:
        if by_lang.get(key):
            return by_lang[key][0]
    return list(by_lang.values())[0][0] if by_lang else ""


def _all_titles(row: dict) -> list[str]:
    out: list[str] = []
    for key in ("title", "alttitle"):
        value = (row.get(key) or "").strip()
        if value and value not in out:
            out.append(value)
    for item in row.get("titles") or []:
        value = (item.get("title") or "").strip()
        if value and value not in out:
            out.append(value)
    return out


class VNDBSource(Source):
    id = "vndb"
    name = "VNDB"
    kind = "api"
    homepage = "https://vndb.org/"
    search_url = "https://vndb.org/v?q={query}"
    supports_lang = True

    def search(self, queries: list[str], timeout: float = 9.0) -> list[Candidate]:
        pool: dict[str, dict] = {}
        for query in queries[:2]:
            key = f"search|{query}"
            cached = net.cache_get("vndb", key, SEARCH_TTL)
            if cached is not None:
                rows = cached.get("rows", [])
            else:
                payload = net.fetch_json(API, method="POST", timeout=timeout, body={
                    "filters": ["search", "=", query],
                    "fields": SEARCH_FIELDS,
                    "results": 10,
                }, attempts=1)
                rows = (payload or {}).get("results") or []
                if payload is not None:
                    net.cache_put("vndb", key, {"rows": rows})
            for row in rows:
                if row.get("id"):
                    pool.setdefault(row["id"], row)

        out = []
        for row in pool.values():
            titles = _all_titles(row)
            if not titles:
                continue
            out.append(Candidate(
                source=self.id,
                source_id=row["id"],
                name=_pick_title(row.get("titles") or [], "zh") or titles[0],
                names=titles,
                cover=(row.get("image") or {}).get("url", ""),
                thumb=(row.get("image") or {}).get("url", ""),
                extra={"id": row["id"]},
            ))
        return out

    def fetch(self, candidate: Candidate, lang: str = "schinese",
              timeout: float = 9.0) -> Metadata | None:
        vid = candidate.source_id
        key = f"detail|{vid}"
        cached = net.cache_get("vndb", key, DETAIL_TTL)
        if cached is not None:
            row = cached.get("row") or {}
        else:
            payload = net.fetch_json(API, method="POST", timeout=timeout, body={
                "filters": ["id", "=", vid],
                "fields": DETAIL_FIELDS,
                "results": 1,
            })
            if payload is None:
                return None
            results = payload.get("results") or []
            if not results:
                return None
            row = results[0]
            net.cache_put("vndb", key, {"row": row})

        titles = row.get("titles") or []
        name_cn = ""
        for item in titles:
            if (item.get("lang") or "").lower().startswith("zh") and item.get("title"):
                name_cn = item["title"]
                break
        display = _pick_title(titles, lang) or row.get("title") or candidate.name

        images: list[dict] = []
        cover = (row.get("image") or {}).get("url", "") or candidate.cover
        if cover:
            images.append({"url": cover, "kind": "cover", "label": "VNDB 封面", "thumb": cover})
        for index, shot in enumerate(row.get("screenshots") or [], start=1):
            url = shot.get("url") or ""
            if not url:
                continue
            images.append({
                "url": url, "kind": "screenshot", "label": f"VNDB 截图 {index}",
                "thumb": shot.get("thumbnail") or url,
            })

        tags = []
        for tag in sorted(row.get("tags") or [], key=lambda t: -(t.get("rating") or 0)):
            name = tag.get("name")
            if name and (tag.get("rating") or 0) >= 1.5 and name not in tags:
                tags.append(name)
            if len(tags) >= 6:
                break

        developers = [d.get("name") for d in (row.get("developers") or []) if d.get("name")]
        rating = row.get("rating")
        minutes = row.get("length_minutes")

        return Metadata(
            source=self.id,
            source_id=vid,
            source_url=f"https://vndb.org/{vid}",
            name=display,
            name_cn=name_cn,
            name_original=row.get("alttitle") or row.get("title") or "",
            description=(row.get("description") or "")[:400],
            about=(row.get("description") or "")[:6000],
            developers=developers,
            publishers=[],
            genres=tags,
            release_date=row.get("released") or "",
            rating=(f"VNDB {rating / 10:.1f}" if isinstance(rating, (int, float)) else ""),
            cover=cover,
            cover_sources=[cover] if cover else [],
            images=images,
            website="",
        )
