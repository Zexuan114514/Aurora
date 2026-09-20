"""简介翻译用例服务（P3.8-c）：单条/批量翻译、常驻队列、接口自测。

从 aurora/ui/bridge/metadata.py 原样搬出；事件改为向默认总线发布（Api 通配订阅推前端）。
翻译请求本身由注入的 LineTranslator 负责（它自带缓存/流式/术语表）。
"""
from __future__ import annotations

import queue
import threading

from aurora.app.events import default_bus
from aurora.app.projection import _public
from gl import config, translate   # TODO(P3.8): 收口到 aurora.infra


class TranslationService:
    """简介翻译：单条、批量与常驻队列（状态都在本服务内）。"""

    def __init__(self, library, pm, translator, tasks) -> None:
        self._library = library
        self._pm = pm
        self._translator = translator
        self._tasks = tasks
        self._translating: set[str] = set()
        self._queue: "queue.Queue[tuple[str, bool]]" = queue.Queue()
        self._worker_started = False
        self._batching = False      # 批量翻译期间用「安静模式」推送
        self._lock = threading.RLock()

    def translate_game(self, game_id: str) -> dict:
        """手动翻译单个游戏的简介（不受自动翻译开关限制）。"""
        if not self._library.get(game_id):
            return {"ok": False, "error": "no-game"}
        self._translate_async(game_id, force=True)
        return {"ok": True}

    def _translate_description(self, game_id: str) -> dict:
        """翻译单个游戏的简介（自动 / 批量 / 手动共用）。"""
        with self._lock:
            if game_id in self._translating:
                return {"ok": False, "changed": False, "error": "busy"}
            self._translating.add(game_id)
        try:
            game = self._library.get(game_id)
            if not game:
                return {"ok": False, "changed": False, "error": "no-game"}
            text = (game.get("description_original") or game.get("description") or "").strip()
            if not text:
                return {"ok": False, "changed": False, "error": "empty"}
            settings = dict(self._library.settings)
            res = translate.translate_text(
                text, target=str(settings.get("translate_target") or translate.TARGET_DEFAULT),
                settings=settings)
            # 陈旧保护：翻译期间若被并发重新抓取换掉了简介，就丢弃这次结果
            current = self._library.get(game_id)
            if not current or (current.get("description_original")
                               or current.get("description") or "").strip() != text:
                return {"ok": False, "changed": False, "error": "stale"}
            fields = {"description_original": text, "description_lang": res["lang"]}
            if res.get("changed"):
                fields["description"] = res["text"]
                fields["description_translated"] = res["text"]
            updated = self._library.update(game_id, **fields)
            if updated:
                default_bus().publish("game:updated", _public(updated, self._pm))
            return {"ok": bool(res.get("changed")), "changed": bool(res.get("changed")),
                    "provider": res.get("provider"), "lang": res.get("lang")}
        finally:
            with self._lock:
                self._translating.discard(game_id)

    def _translate_async(self, game_id: str, force: bool = False) -> None:
        """把翻译任务丢进常驻队列线程。

        force=True 用于用户手动触发（不受「导入后自动翻译」开关限制）。
        """
        if not force and not self._library.settings.get("translate_enabled", True):
            return
        if not self._worker_started:
            self._worker_started = True
            self._tasks.spawn("metadata.translate_q", self._translate_queue_loop,
                                   thread_name="aurora-translate-q")
        self._queue.put((game_id, bool(force)))

    def translate_all_descriptions(self) -> dict:
        """批量翻译库里所有非中文的简介（后台跑，进度用事件推给前端）。"""
        if self._batching:
            return {"ok": False, "error": "busy"}
        ids = [g["id"] for g in self._library.all()
               if (g.get("description") or g.get("description_original"))]
        if not ids:
            return {"ok": False, "error": "empty"}
        self._tasks.spawn("metadata.translate_all", self._translate_all_worker, ids,
                               thread_name="aurora-translate-all")
        return {"ok": True, "total": len(ids)}

    def _translate_all_worker(self, ids: list[str]) -> None:
        self._batching = True
        translated = skipped = failed = 0
        try:
            total = len(ids)
            for index, game_id in enumerate(ids):
                if not self._library.get(game_id):
                    continue
                default_bus().publish("batch:progress",
                           {"done": index, "total": total, "kind": "translate"})
                res = self._translate_description(game_id)
                if res.get("changed"):
                    translated += 1
                elif res.get("error"):
                    failed += 1
                else:
                    skipped += 1
            default_bus().publish("batch:progress",
                       {"done": total, "total": total, "kind": "translate"})
        finally:
            self._batching = False
            default_bus().publish("batch:done", {
                "total": len(ids), "kind": "translate",
                "translated": translated, "skipped": skipped, "failed": failed,
            })

    def _translate_queue_loop(self) -> None:
        while True:
            item = self._queue.get()
            game_id, manual = item if isinstance(item, tuple) else (item, False)
            try:
                res = self._translate_description(game_id)
                # 用户手动点的「翻译简介」要有回执，自动翻译保持安静
                if manual:
                    default_bus().publish("translate:done", {"id": game_id, "manual": True, **res})
            except Exception as exc:  # pragma: no cover
                config.log(f"translate queue error: {exc}")
            finally:
                self._queue.task_done()

    def test_translation(self, overrides: dict | None = None) -> dict:
        """设置面板的「测试」按钮：实时验证翻译接口是否可用。"""
        settings = dict(self._library.settings)
        if isinstance(overrides, dict):
            settings.update({k: v for k, v in overrides.items() if v is not None})
        return translate.test_provider(settings)
