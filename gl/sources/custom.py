"""用户自定义资料源。

两种形态：
1. kind="api"  —— 有 JSON 接口的站点：填 URL 模板 + 字段映射即可
2. kind="link" —— 禁止抓取或纯前端的站点：只生成搜索链接，点一下用浏览器打开
"""
from __future__ import annotations

import re
import uuid

from . import net
from .base import Candidate, Metadata, Source

_INDEX = re.compile(r"\[(\d+|\*)\]")


def get_path(data, path: str):
    """按 "a.b[0].c" / "a[*].b" 取值，支持用 "||" 给多个候选路径。"""
    if not path:
        return None
    for candidate in str(path).split("||"):
        value = _get_single(data, candidate.strip())
        if value not in (None, "", [], {}):
            return value
    return None


def _get_single(data, path: str):
    if not path:
        return None
    current = [data]
    for token in _split(path):
        nxt = []
        for node in current:
            if node is None:
                continue
            if isinstance(token, int):
                if isinstance(node, list) and -len(node) <= token < len(node):
                    nxt.append(node[token])
            elif token == "*":
                if isinstance(node, list):
                    nxt.extend(node)
            elif isinstance(node, dict):
                nxt.append(node.get(token))
            elif isinstance(node, list):
                for row in node:
                    if isinstance(row, dict) and token in row:
                        nxt.append(row.get(token))
        current = nxt
    if len(current) == 1:
        return current[0]
    return [c for c in current if c not in (None, "")]


def _split(path: str) -> list:
    tokens: list = []
    for part in path.split("."):
        if not part:
            continue
        pos = 0
        for match in _INDEX.finditer(part):
            if match.start() > pos:
                tokens.append(part[pos:match.start()])
            index = match.group(1)
            tokens.append("*" if index == "*" else int(index))
            pos = match.end()
        if pos < len(part):
            tokens.append(part[pos:])
    return tokens


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("name") or item.get("v") or ""
            text = str(item or "").strip()
            if text and text not in out:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


class CustomApiSource(Source):
    """用户自定义的 JSON 接口源。"""

    kind = "api"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.id = cfg.get("id") or f"custom:{uuid.uuid4().hex[:8]}"
        self.name = cfg.get("name") or "自定义源"
        self.homepage = cfg.get("homepage") or ""
        self.search_url = cfg.get("search_url") or ""
        self.method = (cfg.get("method") or "GET").upper()
        self.results_path = cfg.get("results_path") or "data"
        self.fields = cfg.get("fields") or {}
        self.detail_url = cfg.get("detail_url") or ""
        self.headers = cfg.get("headers") or {}

    def _query(self, query: str, timeout: float):
        if not self.search_url:
            return None
        url = self.search_url.replace("{query}", net.quote(query))
        body = None
        if self.method == "POST":
            key = self.cfg.get("body_key") or "keyword"
            body = {key: query}
        payload = net.fetch_json(url, method=self.method, body=body,
                                 headers=dict(self.headers), timeout=timeout)
        if payload is None:
            return None
        rows = get_path(payload, self.results_path)
        if rows is None:
            rows = payload if isinstance(payload, list) else []
        if isinstance(rows, dict):
            rows = [rows]
        return rows if isinstance(rows, list) else []

    def search(self, queries: list[str], timeout: float = 9.0) -> list[Candidate]:
        pool: dict[str, dict] = {}
        for query in queries[:2]:
            for row in self._query(query, timeout) or []:
                if not isinstance(row, dict):
                    continue
                sid = str(get_path(row, self.fields.get("id", "id")) or "").strip()
                if not sid:
                    sid = str(len(pool))
                pool.setdefault(sid, row)

        out = []
        for sid, row in pool.items():
            name = get_path(row, self.fields.get("name", "name")) or ""
            names = _as_list(name) + _as_list(get_path(row, self.fields.get("alt_names", "")))
            if not names:
                continue
            cover = str(get_path(row, self.fields.get("cover", "cover")) or "")
            out.append(Candidate(
                source=self.id,
                source_id=sid,
                name=names[0],
                names=names,
                cover=cover,
                thumb=cover,
                extra={"row": row},
            ))
        return out

    def fetch(self, candidate: Candidate, lang: str = "schinese",
              timeout: float = 9.0) -> Metadata | None:
        row = candidate.extra.get("row") or {}
        if self.detail_url:
            url = (self.detail_url.replace("{id}", net.quote(candidate.source_id))
                   .replace("{query}", net.quote(candidate.name)))
            payload = net.fetch_json(url, headers=dict(self.headers), timeout=timeout)
            if isinstance(payload, dict):
                row = payload

        cover = str(get_path(row, self.fields.get("cover", "cover")) or "")
        images: list[dict] = []
        if cover:
            images.append({"url": cover, "kind": "cover", "label": f"{self.name} 封面",
                           "thumb": cover})
        for index, url in enumerate(_as_list(get_path(row, self.fields.get("screenshots", ""))), 1):
            images.append({"url": url, "kind": "screenshot",
                           "label": f"{self.name} 截图 {index}", "thumb": url})

        name = _as_list(get_path(row, self.fields.get("name", "name")))
        name_cn = str(get_path(row, self.fields.get("name_cn", "")) or "").strip()
        description = str(get_path(row, self.fields.get("description", "description")) or "")
        about = str(get_path(row, self.fields.get("about", "")) or "") or description

        return Metadata(
            source=self.id,
            source_id=candidate.source_id,
            source_url=str(get_path(row, self.fields.get("url", "url")) or self.homepage),
            name=name_cn or (name[0] if name else candidate.name),
            name_cn=name_cn,
            name_original=(name[0] if name else ""),
            description=net.clean_html(description)[:400],
            about=net.clean_html(about)[:6000],
            developers=_as_list(get_path(row, self.fields.get("developers", ""))),
            publishers=_as_list(get_path(row, self.fields.get("publishers", ""))),
            genres=_as_list(get_path(row, self.fields.get("genres", "")))[:6],
            categories=_as_list(get_path(row, self.fields.get("categories", "")))[:8],
            release_date=str(get_path(row, self.fields.get("release_date", "")) or ""),
            rating=str(get_path(row, self.fields.get("rating", "")) or ""),
            cover=cover,
            cover_sources=[cover] if cover else [],
            images=images,
        )


class CustomLinkSource(Source):
    """只能跳转搜索的源（例如 TouchGal 这类禁止抓取的站点）。"""

    kind = "link"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.id = cfg.get("id") or f"custom:{uuid.uuid4().hex[:8]}"
        self.name = cfg.get("name") or "搜索站点"
        self.homepage = cfg.get("homepage") or ""
        self.search_url = cfg.get("search_url") or ""

    def search(self, queries: list[str], timeout: float = 9.0) -> list[Candidate]:
        return []

    def fetch(self, candidate: Candidate, lang: str = "schinese",
              timeout: float = 9.0) -> Metadata | None:
        return None


def from_config(cfg: dict) -> Source | None:
    kind = (cfg or {}).get("kind") or "api"
    if kind == "link":
        return CustomLinkSource(cfg)
    if kind == "api":
        return CustomApiSource(cfg)
    return None
