"""资料源的数据结构与基类。"""
from __future__ import annotations

from dataclasses import dataclass, field


# P1：数据契约搬到 aurora.domain.contracts，这里保留同名转发供资料源使用
from aurora.domain.contracts import Candidate, Metadata  # noqa: F401



class Source:
    """资料源基类。

    kind = "api"   ：能搜索 + 拉取详情
    kind = "link"  ：只提供搜索链接（用于禁止抓取或纯前端的站点）
    """

    id = "base"
    name = "基础源"
    kind = "api"
    homepage = ""
    #: link 源的搜索链接模板，{query} 会被替换成关键词
    search_url = ""
    #: 该源用哪种语言的简介（影响 lang 参数）
    supports_lang = False

    def available(self) -> bool:
        return True

    def status(self) -> str:
        return "可用" if self.available() else "不可用"

    def search(self, queries: list[str], timeout: float = 9.0) -> list[Candidate]:
        raise NotImplementedError

    def fetch(self, candidate: Candidate, lang: str = "schinese",
              timeout: float = 9.0) -> Metadata | None:
        raise NotImplementedError

    def link_for(self, query: str) -> str:
        if not self.search_url:
            return self.homepage
        from .net import quote
        return self.search_url.replace("{query}", quote(query))
