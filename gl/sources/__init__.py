"""资料源包：Steam / VNDB / Bangumi + 用户自定义源。"""

from .base import Candidate, Metadata, Source
from .manager import DEFAULT_CONFIG, SourceManager

__all__ = ["Candidate", "Metadata", "Source", "SourceManager", "DEFAULT_CONFIG"]
