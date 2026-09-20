"""代理路线解析原语：手动 / 环境变量 / Windows 系统代理 / 直连（P3.9 从 gl/netproxy.py 搬入）。"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request

_state = {"settings": lambda: {}}


def set_settings_provider(fn) -> None:
    """由 api.py 注入：返回当前设置字典。"""
    _state["settings"] = fn or (lambda: {})


def _normalize(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    try:
        parts = urllib.parse.urlsplit(value)
    except Exception:
        return ""
    if parts.scheme not in ("http", "https", "socks4", "socks5") or not parts.hostname:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _env_proxy() -> tuple[str, str]:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                 "ALL_PROXY", "all_proxy"):
        value = os.environ.get(name)
        if value and value.strip():
            proxy = _normalize(value)
            if proxy:
                return proxy, f"环境变量 {name}"
    return "", ""


def _registry_proxy() -> tuple[str, str]:
    try:
        import winreg

        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            try:
                enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            except OSError:
                enabled = 0
            if not enabled:
                return "", ""
            raw = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
    except Exception:
        return "", ""
    if not raw:
        return "", ""
    if "=" in raw:      # http=1.2.3.4:80;https=1.2.3.4:443
        parts = {}
        for chunk in raw.split(";"):
            if "=" in chunk:
                name, value = chunk.split("=", 1)
                parts[name.strip().lower()] = value.strip()
        raw = parts.get("https") or parts.get("http") or ""
    proxy = _normalize(raw)
    return (proxy, "Windows 系统代理") if proxy else ("", "")


def bypass_list() -> list[str]:
    """不走代理的地址（只用于展示，实际判定交给 urllib 的 proxy_bypass）。"""
    out: list[str] = []
    raw = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    out += [item.strip() for item in raw.split(",") if item.strip()]
    try:
        import winreg

        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            value = str(winreg.QueryValueEx(key, "ProxyOverride")[0] or "")
        out += [item.strip() for item in value.split(";") if item.strip() and item.strip() != "<local>"]
    except Exception:
        pass
    return out


def resolve(settings: dict | None = None) -> dict:
    """当前生效的路线：{mode, proxy, source, fallback}。"""
    cfg = settings if settings is not None else (_state["settings"]() or {})
    cfg = cfg or {}
    mode = str(cfg.get("proxy_mode") or "auto").lower()
    fallback = cfg.get("proxy_fallback", True) is not False

    if mode == "direct":
        return {"mode": "direct", "proxy": "", "source": "手动：直连",
                "fallback": False, "bypass": bypass_list()}
    if mode == "manual":
        proxy = _normalize(str(cfg.get("proxy_url") or ""))
        return {"mode": "manual", "proxy": proxy,
                "source": "手动指定" if proxy else "手动（地址无效或为空）",
                "fallback": fallback, "bypass": bypass_list()}

    proxy, source = _env_proxy()
    if not proxy:
        proxy, source = _registry_proxy()
    return {"mode": "auto", "proxy": proxy, "source": source or "系统（未启用代理）",
            "fallback": fallback, "bypass": bypass_list()}


def current() -> dict:
    return resolve()


def build_opener(proxy: str, context=None):
    """proxy 为空 = 强制直连；否则所有 http/https 都走它。"""
    if proxy:
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]
    else:
        handlers = [urllib.request.ProxyHandler({})]  # 显式禁用环境/系统代理
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def describe() -> dict:
    route = current()
    return {
        "ok": True,
        "mode": route["mode"],
        "proxy": route["proxy"],
        "source": route["source"],
        "fallback": route["fallback"],
        "bypass": route["bypass"][:12],
    }
