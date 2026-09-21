"""调研 galgame 资料源的可行性：VNDB / Bangumi / TouchGal。"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "probe-sources.txt"
UA = "AuroraGameLauncher/1.0 (personal game library tool)"
lines: list[str] = []


def get(url: str, headers=None, timeout=15, method="GET", body=None):
    req = urllib.request.Request(url, method=method, data=body,
                                 headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}".encode()


def show(title: str, url: str, headers=None, keep=520, method="GET", body=None):
    status, raw = get(url, headers, method=method, body=body)
    lines.append(f"--- {title}")
    lines.append(f"    {method} {url}")
    lines.append(f"    status={status} len={len(raw) if raw else 0}")
    if raw:
        text = raw.decode("utf-8", "replace").replace("\n", " ")
        lines.append("    " + text[:keep])
    lines.append("")


# ---------------- VNDB ----------------
show("VNDB 搜索 API",
     "https://api.vndb.org/kana/vn",
     headers={"Content-Type": "application/json"},
     method="POST",
     body=json.dumps({
         "filters": ["search", "=", "千恋万花"],
         "fields": "id,title,alttitle,image.url,description,released,developers.name,"
                   "titles.title,titles.lang,length_minutes,screenshots.url,screenshots.thumbnail",
         "results": 3,
     }).encode())

show("VNDB 英文搜索",
     "https://api.vndb.org/kana/vn",
     headers={"Content-Type": "application/json"},
     method="POST",
     body=json.dumps({
         "filters": ["search", "=", "Sabbat of the Witch"],
         "fields": "id,title,alttitle,image.url,titles.title,titles.lang",
         "results": 3,
     }).encode())

# ---------------- Bangumi ----------------
show("Bangumi 搜索 API",
     "https://api.bgm.tv/v0/search/subjects",
     headers={"Content-Type": "application/json"},
     method="POST",
     body=json.dumps({
         "keyword": "千恋万花",
         "filter": {"type": [4]},
     }).encode())

show("Bangumi 条目详情",
     "https://api.bgm.tv/v0/subjects/210073")

show("Bangumi 旧版搜索",
     "https://api.bgm.tv/search/subject/" + urllib.parse.quote("千恋万花") + "?type=4&responseGroup=small")

# ---------------- TouchGal ----------------
show("TouchGal robots.txt", "https://www.touchgal.ink/robots.txt")
show("TouchGal 首页", "https://www.touchgal.ink/", keep=300)
show("TouchGal 搜索页", "https://www.touchgal.ink/search?query=" + urllib.parse.quote("千恋万花"), keep=300)
show("TouchGal 疑似 API", "https://www.touchgal.ink/api/search?query=" + urllib.parse.quote("千恋万花"))
show("TouchGal 疑似 API2", "https://api.touchgal.ink/api/search?q=" + urllib.parse.quote("千恋万花"))

# ---------------- 其它候选 ----------------
show("VNDB 是否需 token", "https://api.vndb.org/kana/schema")
show("ErogameScape", "https://erogamescape.dyndns.org/~ap2/ero/toukei_kaiseki/")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
