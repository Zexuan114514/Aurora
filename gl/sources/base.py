"""资料源的数据结构与基类。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Candidate:
    """搜索命中的一个候选条目。"""
    source: str                     # 资料源 id，如 "steam" / "vndb"
    source_id: str                  # 源内的唯一 id
    name: str                       # 展示名（优先中文）
    names: list[str] = field(default_factory=list)   # 所有已知名称，用于打分
    score: float = 0.0
    thumb: str = ""
    cover: str = ""
    extra: dict = field(default_factory=dict)        # 拉详情时要用的原始数据

    def to_public(self) -> dict:
        return {
            "source": self.source,
            "source_id": str(self.source_id),
            "name": self.name,
            "thumb": self.thumb or self.cover,
            "cover": self.cover,
            "score": round(self.score, 4),
        }


@dataclass
class Metadata:
    """统一的元数据结果。"""
    source: str
    source_id: str
    source_url: str = ""
    name: str = ""
    name_cn: str = ""
    name_original: str = ""
    description: str = ""          # 短简介
    about: str = ""                # 长简介
    developers: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)   # 玩法特性：单人 / Steam 成就 / 云存档…
    release_date: str = ""
    rating: str = ""               # 形如 "Bangumi 7.8" / "VNDB 8.2" / "Metacritic 94"
    cover: str = ""
    cover_sources: list[str] = field(default_factory=list)
    logo: str = ""
    images: list[dict] = field(default_factory=list)
    website: str = ""
    header_image: str = ""

    def merge_images(self, other: "Metadata") -> None:
        """把另一个源的图片并进来（去重，保留先来的顺序）。"""
        seen = {img.get("url") for img in self.images}
        for img in other.images:
            url = (img.get("url") or "").split("?")[0]
            if url and url not in seen:
                seen.add(url)
                self.images.append({**img, "url": url})
        for url in other.cover_sources:
            if url and url not in self.cover_sources:
                self.cover_sources.append(url)
        if not self.logo and other.logo:
            self.logo = other.logo
        if not self.header_image and other.header_image:
            self.header_image = other.header_image
        self.merge_missing(other)

    #: 可以被其它源补齐的字段（本条目为空时才填）
    TEXT_FIELDS = ("description", "about", "release_date", "rating", "website", "cover")
    LIST_FIELDS = ("developers", "publishers", "genres", "categories")

    def merge_missing(self, other: "Metadata") -> None:
        """补齐本条目缺失的文字信息（已有内容不被覆盖）。

        Bangumi 的 R18 条目在接口里只返回名称与封面，靠这一步用 VNDB / Steam
        的简介、开发商等把详情补全。
        """
        for field in self.TEXT_FIELDS:
            if not getattr(self, field, "") and getattr(other, field, ""):
                setattr(self, field, getattr(other, field))
        for field in self.LIST_FIELDS:
            if not getattr(self, field, None):
                values = list(getattr(other, field, None) or [])
                if values:
                    setattr(self, field, values)

    def to_public(self) -> dict:
        return {
            "source": self.source,
            "source_id": str(self.source_id),
            "source_url": self.source_url,
            "name": self.name,
            "name_cn": self.name_cn,
            "name_original": self.name_original,
            "description": self.description,
            "about": self.about,
            "developers": self.developers,
            "publishers": self.publishers,
            "genres": self.genres,
            "categories": self.categories,
            "release_date": self.release_date,
            "rating": self.rating,
            "cover": self.cover,
            "cover_sources": self.cover_sources,
            "logo": self.logo,
            "images": self.images,
            "website": self.website,
            "header_image": self.header_image,
        }


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
