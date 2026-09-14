"""Steam 商店资料源（公开接口，无需 API Key）。"""
from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from ..detect import has_cjk
from . import net
from .base import Candidate, Metadata, Source

SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
DETAILS_URL = "https://store.steampowered.com/api/appdetails"
CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps"

SEARCH_TTL = 7 * 24 * 3600
DETAILS_TTL = 30 * 24 * 3600
IMAGE_TTL = 21 * 24 * 3600
BAD_TTL = 3 * 3600

# 封面候选顺序：先用稳定的 cdn.cloudflare 资源，再退回商店接口给的地址
COVER_CANDIDATES = (
    "library_600x900.jpg", "library_600x900_2x.jpg", "capsule_616x353.jpg",
    "header.jpg", "capsule_231x87.jpg", "library_hero.jpg",
)


def _langs_for(query: str) -> list[tuple[str, str]]:
    if has_cjk(query):
        return [("schinese", "CN"), ("english", "US")]
    return [("english", "US"), ("schinese", "CN")]


def _search_terms(query: str) -> list[str]:
    """中文关键词常因标点/后缀搜不到，补充前缀退化尝试。"""
    terms = [query]
    if has_cjk(query) and len(query) > 3:
        for cut in (len(query) - 1, len(query) - 2, 3):
            if cut < 2 or cut >= len(query):
                continue
            prefix = query[:cut]
            if prefix not in terms:
                terms.append(prefix)
    return terms[:3]


def _check_image(url: str) -> tuple[str, bool]:
    cached = net.cache_get_ttl("imgcheck", url, IMAGE_TTL, BAD_TTL)
    if cached is not None:
        return url, bool(cached.get("ok"))
    ok = False
    try:
        resp = net.fetch(url, headers={"Range": "bytes=0-64"}, timeout=8, attempts=1)
        ok = bool(resp)
    except Exception:
        ok = False
    net.cache_put("imgcheck", url, {"ok": ok})
    return url, ok


def _check_many(urls: list[str]) -> dict[str, bool]:
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
        return dict(pool.map(_check_image, urls))


class SteamSource(Source):
    id = "steam"
    name = "Steam 商店"
    kind = "api"
    homepage = "https://store.steampowered.com/"
    search_url = "https://store.steampowered.com/search/?term={query}"
    supports_lang = True

    # ------------------------------------------------------------------ #
    # 搜索
    # ------------------------------------------------------------------ #
    def _search_once(self, term: str, lang: str, cc: str,
                     timeout: float) -> list[dict] | None:
        key = f"{term}|{lang}|{cc}"
        cached = net.cache_get("search", key, SEARCH_TTL)
        if cached is not None:
            return cached.get("items", [])
        url = f"{SEARCH_URL}?{urllib.parse.urlencode({'term': term, 'cc': cc, 'l': lang})}"
        # 搜索不重试：一个源卡住会把整个搜索预算耗光（详情请求才值得重试）
        payload = net.fetch_json(url, timeout=timeout, attempts=1)
        if payload is None:
            return None
        items = []
        for item in payload.get("items", []) or []:
            if item.get("type") != "app":
                continue
            try:
                appid = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            items.append({
                "appid": appid,
                "name": item.get("name") or "",
                "tiny_image": item.get("tiny_image") or "",
                "type": item.get("type"),
            })
        if items:
            net.cache_put("search", key, {"items": items})
        return items

    def search(self, queries: list[str], timeout: float = 9.0) -> list[Candidate]:
        pool: dict[int, dict] = {}
        for query in queries[:2]:
            for term in _search_terms(query):
                failed = False
                for lang, cc in _langs_for(term):
                    items = self._search_once(term, lang, cc, timeout)
                    if items is None:
                        failed = True
                        continue
                    for item in items:
                        entry = pool.setdefault(item["appid"], {
                            "appid": item["appid"], "names": [], "tiny_image": item["tiny_image"]})
                        if item["name"] and item["name"] not in entry["names"]:
                            entry["names"].append(item["name"])
                if failed and not pool:
                    break
        out = []
        for entry in pool.values():
            out.append(Candidate(
                source=self.id,
                source_id=str(entry["appid"]),
                name=entry["names"][0] if entry["names"] else "",
                names=list(entry["names"]),
                thumb=entry.get("tiny_image", ""),
                extra={"appid": entry["appid"]},
            ))
        return out

    # ------------------------------------------------------------------ #
    # 详情
    # ------------------------------------------------------------------ #
    def _details(self, appid: int, lang: str, cc: str, timeout: float) -> dict | None:
        key = f"{appid}|{lang}|{cc}"
        cached = net.cache_get("details", key, DETAILS_TTL)
        if cached is not None:
            return cached.get("data")
        url = f"{DETAILS_URL}?{urllib.parse.urlencode({'appids': appid, 'cc': cc, 'l': lang})}"
        payload = net.fetch_json(url, timeout=timeout)
        if payload is None:
            return None
        entry = payload.get(str(appid)) or {}
        data = entry.get("data") if entry.get("success") else None
        if data:
            net.cache_put("details", key, {"data": data})
        return data

    def fetch(self, candidate: Candidate, lang: str = "schinese",
              timeout: float = 9.0) -> Metadata | None:
        appid = int(candidate.source_id)
        probe = [f"{CDN}/{appid}/{name}" for name in
                 ("library_hero.jpg", "library_hero_blur.jpg", "page_bg_generated_v6b.jpg",
                  "logo.png")]
        with ThreadPoolExecutor(max_workers=2) as pool:
            details_future = pool.submit(self._details, appid, lang, "CN", timeout)
            checks_future = pool.submit(_check_many, probe)
            details = details_future.result()
            checks = checks_future.result()

        if details is None and lang != "english":
            details = self._details(appid, "english", "US", timeout)
        details = details or {}

        images: list[dict] = []

        def push(url: str, kind: str, label: str, thumb: str = "") -> None:
            url = (url or "").split("?")[0]
            if not url or any(row["url"] == url for row in images):
                return
            images.append({"url": url, "kind": kind, "label": label, "thumb": thumb or url})

        for name, label in (("library_hero.jpg", "官方封面图"),
                            ("library_hero_blur.jpg", "官方封面图 · 柔焦"),
                            ("page_bg_generated_v6b.jpg", "商店页面背景")):
            url = f"{CDN}/{appid}/{name}"
            if checks.get(url):
                push(url, "hero", label)
        push(details.get("background_raw", ""), "art", "原始背景")
        push(details.get("background", ""), "art", "商店背景")
        push(details.get("header_image", ""), "header", "头图")
        for index, shot in enumerate(details.get("screenshots") or [], start=1):
            push(shot.get("path_full", ""), "screenshot", f"截图 {index}",
                 shot.get("path_thumbnail", ""))

        cover_sources: list[str] = []
        for name in COVER_CANDIDATES:
            cover_sources.append(f"{CDN}/{appid}/{name}")
        for key in ("capsule_imagev5", "capsule_image", "header_image", "background_raw"):
            url = (details.get(key) or "").split("?")[0]
            if url and url not in cover_sources:
                cover_sources.append(url)

        genres = [g.get("description", "") for g in (details.get("genres") or [])
                  if g.get("description")]
        categories = [c.get("description", "") for c in (details.get("categories") or [])
                      if c.get("description")]
        metacritic = (details.get("metacritic") or {}).get("score")

        return Metadata(
            source=self.id,
            source_id=str(appid),
            source_url=f"https://store.steampowered.com/app/{appid}/",
            name=details.get("name") or candidate.name,
            name_cn=details.get("name") or "",
            name_original="",
            description=net.clean_html(details.get("short_description") or ""),
            about=net.clean_html(details.get("detailed_description") or "")[:6000],
            developers=details.get("developers") or [],
            publishers=details.get("publishers") or [],
            genres=genres[:6],
            categories=categories[:8],
            release_date=(details.get("release_date") or {}).get("date", ""),
            rating=f"Metacritic {metacritic}" if metacritic else "",
            cover=cover_sources[0] if cover_sources else "",
            cover_sources=cover_sources,
            logo=f"{CDN}/{appid}/logo.png" if checks.get(f"{CDN}/{appid}/logo.png") else "",
            images=images,
            website=details.get("website") or "",
            header_image=details.get("header_image") or "",
        )
