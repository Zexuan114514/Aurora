"""设置 / 资料源 / 站点 / 下载 / 转区 / 网络 桥接（P3.2 从 gl/api.py 原样搬出）。

方法体逐字未改；`gl` 遗留依赖在 P3.3 收口到 aurora.infra / aurora.platform。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from gl import config, downloads, locale, netproxy, vntext   # TODO(P3.8): 逐个收口
from gl.sources import net


class SettingsBridgeMixin:
    """设置页、资料源与站点管理、下载与转区选项、网络诊断。"""


    def set_setting(self, key: str, value) -> dict:
        return self._settings.set_setting(key, value)


    # ------------------------------------------------------------------ #
    # 插件（P6.2，ADR-0009）：状态查询与重新扫描
    # ------------------------------------------------------------------ #
    def list_plugins(self) -> dict:
        """列出 `data/plugins/**` 下的插件与它们的加载状态（失败原因一并返回）。"""
        return self._plugins_service.list()


    def rescan_plugins(self) -> dict:
        """按用户要求重新扫一遍插件目录，并把结果同步给资料源管理器。"""
        payload = self._plugins_service.rescan()
        self._sources.set_plugin_statuses(self._plugins_service.statuses())
        return payload


    # ------------------------------------------------------------------ #
    # 资料源管理
    # ------------------------------------------------------------------ #
    def list_sources(self) -> list[dict]:
        return self._settings.list_sources()


    def toggle_source(self, source_id: str, enabled: bool) -> dict:
        return self._settings.toggle_source(source_id, enabled)


    def move_source(self, source_id: str, delta: int) -> dict:
        return self._settings.move_source(source_id, delta)


    def add_custom_source(self, config_json: dict) -> dict:
        return self._settings.add_custom_source(config_json)


    def remove_custom_source(self, source_id: str) -> dict:
        return self._settings.remove_custom_source(source_id)


    def set_merge_sources(self, enabled: bool) -> dict:
        return self._settings.set_merge_sources(enabled)


    def test_source(self, source_id: str, query: str = "") -> dict:
        return self._sources.test(source_id, query or "千恋万花")


    # ------------------------------------------------------------------ #
    # 获取游戏：Steam 发现 / 一键安装 / 下载目录
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # 获取游戏：资源站（自己增删，点一下用默认浏览器打开）
    # ------------------------------------------------------------------ #
    def _sites(self) -> list[dict]:
        return self._settings.sites()


    def list_sites(self) -> dict:
        return self._settings.list_sites()


    def add_site(self, name: str, url: str) -> dict:
        return self._settings.add_site(name, url)


    def remove_site(self, site_id: str) -> dict:
        return self._settings.remove_site(site_id)


    def get_download_settings(self) -> dict:
        """下载目录 / 监听开关 / 解压开关 / 本机解压器。"""
        return {"ok": True, **self._downloads.status()}


    def set_download_option(self, key: str, value) -> dict:
        """改下载相关设置（目录 / 监听 / 解压）。"""
        if key not in ("download_dir", "download_watch", "download_extract"):
            return {"ok": False, "error": "bad-key"}
        if key == "download_dir":
            path = str(value or "").strip()
            if not path:
                return {"ok": False, "error": "empty"}
            target = Path(path)
            try:
                target.mkdir(parents=True, exist_ok=True)
                probe = target / ".write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink()
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            self._library.set_setting("download_dir", str(target))
            # 换了目录：清掉旧的“已处理”记录，让新目录重新建基线
            self._library.set_setting("download_baseline_dir", "")
            self._library.set_setting("download_seen", [])
        else:
            self._library.set_setting(key, bool(value))
        return {"ok": True, **self._downloads.status()}


    # ------------------------------------------------------------------ #
    # 转区启动（Locale Emulator）
    # ------------------------------------------------------------------ #
    def get_locale_status(self) -> dict:
        settings = self._library.settings
        state = locale.status(str(settings.get("le_proc_path") or ""))
        state["ok"] = True
        state["default_enabled"] = bool(settings.get("locale_default"))
        return state


    def set_locale_option(self, key: str, value) -> dict:
        if key == "locale_default":
            self._library.set_setting("locale_default", bool(value))
        elif key == "le_proc_path":
            path = str(value or "").strip()
            if path:
                ok, err = locale.validate(path)
                if not ok:
                    return {"ok": False, "error": err}
            self._library.set_setting("le_proc_path", path)
        else:
            return {"ok": False, "error": "bad-key"}
        return self.get_locale_status()


    # ------------------------------------------------------------------ #
    # 网络：代理状态与连通性
    # ------------------------------------------------------------------ #
    def get_network_status(self) -> dict:
        return netproxy.describe()


    def set_proxy_option(self, key: str, value) -> dict:
        if key == "proxy_mode":
            mode = str(value or "auto").lower()
            if mode not in ("auto", "direct", "manual"):
                return {"ok": False, "error": "bad-mode"}
            self._library.set_setting("proxy_mode", mode)
        elif key == "proxy_url":
            url = str(value or "").strip()
            if url and not netproxy._normalize(url):
                return {"ok": False, "error": "bad-url"}
            self._library.set_setting("proxy_url", url)
        elif key == "proxy_fallback":
            self._library.set_setting("proxy_fallback", bool(value))
        else:
            return {"ok": False, "error": "bad-key"}
        return netproxy.describe()


    def test_network(self) -> dict:
        """逐个试一下关键端点，把「连不上」变成看得见的结果。"""
        from gl.sources import net

        probes = (
            ("Steam 商店", "https://store.steampowered.com/api/storesearch/?term=neko&cc=CN&l=schinese",
             "GET", None),
            ("Steam 图片", "https://cdn.cloudflare.steamstatic.com/steam/apps/1245620/library_hero.jpg",
             "GET", None),
            ("VNDB", "https://api.vndb.org/kana/vn", "POST",
             {"filters": ["search", "=", "eden"], "fields": "id", "results": 1}),
            ("Bangumi", "https://api.bgm.tv/search/subject/eden?type=4&responseGroup=small",
             "GET", None),
            ("翻译接口", "https://api.mymemory.translated.net/get?q=hello&langpair=en%7Czh-CN",
             "GET", None),
        )
        results = []
        for name, url, method, body in probes:
            started = time.time()
            try:
                payload = json.dumps(body).encode("utf-8") if body else None
                headers = {"Content-Type": "application/json"} if body else None
                net.fetch(url, method=method, body=payload, headers=headers,
                          timeout=10, attempts=1)
                results.append({"name": name, "ok": True,
                                "detail": f"{int((time.time() - started) * 1000)} ms"})
            except Exception as exc:
                results.append({"name": name, "ok": False,
                                "detail": f"{type(exc).__name__}: {str(exc)[:70]}"})
        route = netproxy.current()
        return {"ok": True, "proxy": route["proxy"], "source": route["source"],
                "results": results}
