"""设置 / 站点 / 资料源用例服务（P3.8 从 aurora/ui/bridge/settings.py 搬出）。

桥接方法退化成一行转发；返回结构保持原样，前端契约不变。
"""
from __future__ import annotations

import uuid

from gl import config


class SettingsService:
    """设置快照、资源站 CRUD、资料源配置。"""

    def __init__(self, library, sources) -> None:
        self._library = library
        self._sources = sources

    # ---- 设置 ----
    def snapshot(self) -> dict:
        return dict(self._library.settings)

    def set(self, key: str, value) -> dict:
        return self._library.set_setting(key, value)

    # ---- 资源站 ----
    def sites(self) -> list[dict]:
        raw = self._library.settings.get("resource_sites")
        rows = raw if isinstance(raw, list) else []
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()[:40]
            url = str(row.get("url") or "").strip()
            if not name or not url.startswith(("http://", "https://")):
                continue
            out.append({"id": str(row.get("id") or f"site{len(out):02d}"),
                        "name": name, "url": url[:500]})
        return out

    def list_sites(self) -> dict:
        return {"ok": True, "sites": self.sites()}

    def add_site(self, name: str, url: str) -> dict:
        """添加一个资源站；地址里可以带 {query} 占位符。"""
        name = (name or "").strip()[:40]
        url = (url or "").strip()
        if not name:
            return {"ok": False, "error": "empty-name"}
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "bad-url"}
        sites = self.sites()
        entry = {"id": f"site{uuid.uuid4().hex[:8]}", "name": name, "url": url[:500]}
        sites.append(entry)
        self._library.set_setting("resource_sites", sites)
        config.log(f"resource site added: {name} {url}")
        return {"ok": True, "site": entry, "sites": sites}

    def remove_site(self, site_id: str) -> dict:
        sites = [row for row in self.sites() if row["id"] != site_id]
        self._library.set_setting("resource_sites", sites)
        return {"ok": True, "sites": sites}

    # ---- 资料源 ----
    def list_sources(self) -> list[dict]:
        return self._sources.describe()

    def toggle_source(self, source_id: str, enabled: bool) -> dict:
        self._sources.set_enabled(source_id, bool(enabled))
        return {"ok": True, "sources": self._sources.describe()}

    def move_source(self, source_id: str, delta: int) -> dict:
        self._sources.move(source_id, int(delta))
        return {"ok": True, "sources": self._sources.describe()}

    def add_custom_source(self, config_json: dict) -> dict:
        entry = self._sources.add_custom(config_json or {})
        return {"ok": True, "source": entry, "sources": self._sources.describe()}

    def remove_custom_source(self, source_id: str) -> dict:
        ok = self._sources.remove_custom(source_id)
        return {"ok": ok, "sources": self._sources.describe()}

    def set_merge_sources(self, enabled: bool) -> dict:
        cfg = self._sources.config()
        cfg["merge_images"] = bool(enabled)
        self._sources.save_config(cfg)
        return {"ok": True, "merge_images": cfg["merge_images"]}
