"""兼容层：旧的 metadata 接口转发到 gl.sources。

新代码请直接用 gl.sources.SourceManager；这里保留几个老函数，
方便已有脚本（tools/selftest.py、tools/meta_offline.py 等）继续使用。
"""
from __future__ import annotations

from .sources import SourceManager
from .sources.net import clean_html  # noqa: F401  （重新导出）
from .sources.steam import SteamSource
from .store import Library

_manager: SourceManager | None = None


def manager() -> SourceManager:
    global _manager
    if _manager is None:
        _manager = SourceManager(Library())
    return _manager


def resolve(queries: list[str], threshold: float = 0.75, timeout: float = 9.0,
            budget: float = 60.0, max_queries: int = 2, verify: bool = True) -> dict:
    """跨资料源搜索并打分（Steam / VNDB / Bangumi 等）。"""
    return manager().resolve(queries, threshold=threshold, timeout=timeout,
                             budget=budget, max_queries=max_queries)


def build_metadata(appid: int, lang: str = "schinese", search_thumb: str = "",
                   fallback_name: str = "", timeout: float = 9.0) -> dict:
    """按 Steam appid 拉取元数据（旧接口，内部走 steam 源）。"""
    data = manager().build("steam", str(appid), fallback_name, lang=lang, timeout=timeout)
    return data or {}


def search_store(term: str, lang: str = "english", cc: str = "US",
                 timeout: float = 9.0) -> list[dict] | None:
    """Steam 商店搜索（旧接口）。返回 None 表示请求失败。"""
    items = SteamSource()._search_once(term, lang, cc, timeout)
    if items is None:
        return None
    return [{"appid": row["appid"], "name": row["name"], "tiny_image": row["tiny_image"],
             "type": "app"} for row in items]


def app_details(appid: int, lang: str = "schinese", cc: str = "CN",
                timeout: float = 9.0) -> dict | None:
    """Steam 商店详情（旧接口）。"""
    return SteamSource()._details(int(appid), lang, cc, timeout)
