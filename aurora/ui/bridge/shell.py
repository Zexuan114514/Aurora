"""系统 Shell 与文件对话框桥接（P3 从 gl/api.py 原样搬出）。

包含打开 URL / 目录 / 资源站搜索，以及「选择文件」这一组对话框。
"""
from __future__ import annotations

import os
from pathlib import Path

import webview

from gl import config, process, vntext   # TODO(P3.2): 收口到 aurora.platform / aurora.infra


class ShellBridgeMixin:
    """打开外部资源、定位文件与文件/目录选择对话框。"""


    def open_url(self, url: str) -> dict:
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            try:
                os.startfile(url)  # noqa: S606
                return {"ok": True}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "bad-url"}


    def open_data_dir(self) -> dict:
        try:
            os.startfile(str(config.DATA_DIR))  # noqa: S606
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "dir": str(config.DATA_DIR)}


    def open_download_dir(self) -> dict:
        target = self._downloads.download_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(str(target))  # noqa: S606
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "dir": str(target)}


    def open_language_settings(self) -> dict:
        try:
            os.startfile("ms-settings:regionlanguage")  # noqa: S606
        except Exception:
            try:
                os.startfile("ms-settings:keyboard")  # noqa: S606
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        return {"ok": True}


    def open_source_search(self, query: str, source_id: str = "") -> dict:
        """在指定的“跳转型”源里搜索（用浏览器打开）。"""
        target = None
        for row in self._sources.link_sources():
            if not source_id or row["id"] == source_id:
                target = row
                break
        if target is None:
            return {"ok": False, "error": "no-link-source"}
        source = self._sources.get(target["id"])
        url = source.link_for(query) if source else ""
        if not url:
            return {"ok": False, "error": "no-url"}
        return {**self.open_url(url), "url": url}


    def open_textractor_page(self) -> dict:
        return self.open_url(vntext.TEXTRACTOR_URL)


    def open_site(self, site_id: str, query: str = "") -> dict:
        """用系统默认浏览器打开资源站（带 {query} 的地址会拼上关键词）。"""
        from urllib.parse import quote

        row = next((item for item in self._sites() if item["id"] == site_id), None)
        if row is None:
            return {"ok": False, "error": "not-found"}
        url = row["url"]
        text = str(query or "").strip()
        if "{query}" in url:
            url = url.replace("{query}", quote(text))
        return {**self.open_url(url), "url": url}


    def reveal(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False}
        process.reveal(game["exe"])
        return {"ok": True}


    # ------------------------------------------------------------------ #
    # 导入 / 删除
    # ------------------------------------------------------------------ #
    def pick_executable(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._dialogs.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=("可执行文件 (*.exe;*.bat;*.cmd)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        paths = [str(p) for p in result]
        added = [self._import_one(p) for p in paths]
        games = [g for g in added if g]
        skipped = [p for p, game in zip(paths, added) if not game]
        return {"ok": True, "games": games, "skipped": skipped}


    def pick_download_dir(self) -> dict:
        """让用户挑一个下载目录。"""
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._dialogs.create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return self.set_download_option("download_dir", path)


    def pick_locale_proc(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._dialogs.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("可执行文件 (*.exe)", "所有文件 (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        return self.set_locale_option("le_proc_path", path)


    def pick_textractor(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "no-window"}
        result = self._dialogs.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=False,
            file_types=("命令行程序 (*.exe)", "所有文件 (*.*)"))
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        if not Path(path).is_file():
            return {"ok": False, "error": "not-found"}
        self._library.set_setting("vntext_tractor_path", str(path))
        return {"ok": True, **self._vntext_state()}
