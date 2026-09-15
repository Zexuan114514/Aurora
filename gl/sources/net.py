"""资料源共用的 HTTP、缓存与文本处理工具。"""
from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .. import config, netproxy

_SSL_CTX = ssl.create_default_context()
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_IPV4_LOCK = False

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_END = re.compile(r"</(?:p|div|li|h[1-6]|tr|br)>", re.I)
_BR = re.compile(r"<br\s*/?>", re.I)
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_SPACES = re.compile(r"[ \t\xa0]+")
_MULTINL = re.compile(r"\n{3,}")

#: 累计失败次数。有些源会把「请求失败」当成「没有结果」吞掉，
#: 上层靠这个计数就能区分「真的没搜到」和「网络出问题了」。
_FAILURES = 0


def failures() -> int:
    return _FAILURES


def _note_failure() -> None:
    global _FAILURES
    _FAILURES += 1


def _ipv4_only() -> None:
    """强制 IPv4，绕开偶发的 IPv6 握手超时。"""
    global _IPV4_LOCK
    if _IPV4_LOCK:
        return
    _IPV4_LOCK = True

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        try:
            results = _ORIGINAL_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)
        except Exception:
            results = []
        return results or _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

    socket.getaddrinfo = getaddrinfo


_OPENERS: dict[str, object] = {}


def _opener(proxy: str):
    """按代理路线缓存 opener（ProxyHandler 不便宜，别每次请求都建）。"""
    if proxy not in _OPENERS:
        _OPENERS[proxy] = netproxy.build_opener(proxy, _SSL_CTX)
    return _OPENERS[proxy]


def _request(request, timeout: float, proxy: str) -> bytes:
    with _opener(proxy).open(request, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw


def fetch(url: str, method: str = "GET", body: bytes | None = None,
          headers: dict | None = None, timeout: float = 9.0, attempts: int = 3,
          ua: str | None = None) -> bytes:
    _ipv4_only()
    route = netproxy.current()
    proxy = route.get("proxy") or ""
    last: Exception | None = None

    def new_request() -> urllib.request.Request:
        """每次尝试都要新建：走代理的尝试会改写 Request 的 host/selector，
        复用同一个对象会让后续「直连重试」照样打在代理上。"""
        return urllib.request.Request(
            url,
            method=method,
            data=body,
            headers={
                "User-Agent": ua or config.USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Encoding": "gzip",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                **(headers or {}),
            },
        )

    for attempt in range(attempts):
        try:
            return _request(new_request(), timeout, proxy)
        except Exception as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
    # 走代理失败 → 按设置再试一次直连（代理规则坏掉时能自救）
    if proxy and route.get("fallback", True):
        try:
            result = _request(new_request(), timeout, "")
            config.log(f"proxy failed, direct retry ok: {url.split('?')[0]}")
            return result
        except Exception as exc:
            last = exc
            config.log(f"proxy failed, direct retry failed: {url.split('?')[0]}")
    _note_failure()
    raise last if last else RuntimeError("fetch failed")


def fetch_json(url: str, method: str = "GET", body: dict | None = None,
               headers: dict | None = None, timeout: float = 9.0,
               ua: str | None = None, attempts: int = 3):
    """返回解析后的 JSON；网络失败返回 None（调用方据此区分“没结果”和“请求失败”）。"""
    payload = None
    merged = dict(headers or {})
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        merged.setdefault("Content-Type", "application/json")
    try:
        raw = fetch(url, method=method, body=payload, headers=merged, timeout=timeout,
                    ua=ua, attempts=attempts)
    except Exception as exc:
        config.log(f"{url.split('?')[0]} failed: {exc}")
        return None
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:
        config.log(f"{url.split('?')[0]} bad json: {exc}")
        return None


# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #
def cache_path(namespace: str, key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    safe = re.sub(r"[^0-9a-zA-Z_\-]", "", key)[:40]
    return config.STEAM_CACHE_DIR / namespace / f"{safe}-{digest}.json"


def cache_get(namespace: str, key: str, ttl: float):
    path = cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > ttl:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def cache_put(namespace: str, key: str, value) -> None:
    try:
        config.write_json(cache_path(namespace, key), value)
    except Exception as exc:  # pragma: no cover
        config.log(f"cache write failed: {exc}")


def cache_get_ttl(namespace: str, key: str, good_ttl: float, bad_ttl: float):
    """读缓存：成功结果用长 TTL，失败结果用短 TTL（避免一次抖动被长期记成“不存在”）。"""
    path = cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh)
        ok = bool(value.get("ok")) if isinstance(value, dict) and "ok" in value else True
        if age <= (good_ttl if ok else bad_ttl):
            return value
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# 文本 / 图片
# --------------------------------------------------------------------------- #
def clean_html(raw: str) -> str:
    if not raw:
        return ""
    text = _SCRIPT.sub(" ", raw)
    text = _BR.sub("\n", text)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _SPACES.sub(" ", text)
    text = _MULTINL.sub("\n\n", text)
    return text.strip()


def quote(text: str) -> str:
    return urllib.parse.quote(str(text or ""))
