"""文件对话框适配器（P3.9-h）：把桥接层从 pywebview 的窗口对象上解耦。

实现仍是 pywebview 的 create_file_dialog；没有窗口时返回空（调用方按「取消」处理）。
"""
from __future__ import annotations

import webview


class WebviewFileDialog:
    """按需取窗口的对话框适配器（窗口晚于 Api 创建，所以用 getter）。"""

    def __init__(self, window_getter) -> None:
        self._window_getter = window_getter

    def create_file_dialog(self, dialog_type, **kwargs):
        window = self._window_getter()
        if window is None:
            return None
        return window.create_file_dialog(dialog_type, **kwargs)

    # 便捷常量（调用方可用 webview.OPEN_DIALOG 或端口上的同名常量）
    OPEN_DIALOG = webview.OPEN_DIALOG
    SAVE_DIALOG = webview.SAVE_DIALOG
