"""再探 TouchGal / Kungal 是否提供可用接口（该站已迁移到 kungal.com）。"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "probe-kungal.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
lines: list[str] = []


def probe(url: str, method="GET", body=None, headers=None):
    req = urllib.request.Request(
        url, method=method, data=body,
        headers={"User-Agent": UA, "Accept": "application/json, text/html;q=0.9",
                 **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=15,
                                    context=ssl.create_default_context()) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
    except Exception as e:
        return None, f"{type(e).__name__}: {e}".encode()


CASES = [
    ("kungal 首页", "https://www.kungal.com/", "GET", None),
    ("kungal robots", "https://www.kungal.com/robots.txt", "GET", None),
    ("kungal 搜索页", "https://www.kungal.com/galgame?search=" + urllib.parse.quote("千恋万花"), "GET", None),
    ("kungal api 搜索", "https://www.kungal.com/api/search?q=" + urllib.parse.quote("千恋万花"), "GET", None),
    ("kungal api v1", "https://api.kungal.com/api/galgame?q=" + urllib.parse.quote("千恋万花"), "GET", None),
    ("kungal nuxt data", "https://www.kungal.com/_nuxt/", "GET", None),
    ("touchgal 新域名", "https://touchgal.ink/", "GET", None),
    ("touchgal www 换 UA", "https://www.touchgal.ink/", "GET", None),
    ("SearchGal 仓库", "https://api.github.com/repos/Moe-Sakura/SearchGal", "GET", None),
]

for name, url, method, body in CASES:
    status, raw = probe(url, method, body)
    lines.append(f"--- {name}")
    lines.append(f"    {method} {url}")
    lines.append(f"    status={status} len={len(raw) if raw else 0}")
    if raw:
        lines.append("    " + raw.decode("utf-8", "replace").replace("\n", " ")[:300])
    lines.append("")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
