"""游戏内翻译用例服务·上半（P3.8-f）：翻译面板状态、文本会话启停、悬浮窗、术语表。

从 aurora/ui/bridge/vntext.py 原样搬出；引擎/翻译器/悬浮窗/热键由外部注入。
钩子查找器仍在桥接层（P3.8-g 再搬）。
"""
from __future__ import annotations

import time
from pathlib import Path

from aurora.app.events import default_bus
from gl import config, linetrans, ocr, screencap, vntext   # TODO(P3.8): 收口


class VnTextService:
    """翻译面板与悬浮窗：状态、启停、区域、术语表、事件回推。"""

    def __init__(self, library, pm, engine, translator, overlay, hotkeys, tasks,
                 *, stop_hook_search=None) -> None:
        self._library = library
        self._pm = pm
        self._engine = engine
        self._vn_engine = engine
        self._translator = translator
        self._overlay = overlay
        self._hotkeys = hotkeys
        self._tasks = tasks
        self._lock = __import__("threading").RLock()
        #: 钩子查找器仍在桥接层（P3.8-g 搬完换端口）
        self._stop_hook_search = stop_hook_search

    def _vntext_state(self) -> dict:
        settings = self._library.settings
        cli = vntext.find_cli(str(settings.get("vntext_tractor_path") or ""))
        state = self._vn_engine.status()
        state.update({
            "enabled": bool(settings.get("vntext_enabled")),
            "mode": str(settings.get("vntext_engine") or "auto"),
            "auto_start": bool(settings.get("vntext_auto_start")),
            "tractor": {"found": bool(cli), "path": cli, "url": vntext.TEXTRACTOR_URL,
                        "saved": str(settings.get("vntext_tractor_path") or "")},
            "ocr": ocr.status("ja-JP"),
            "overlay": dict(settings.get("vntext_overlay") or {}),
            "overlay_open": self._overlay.visible(),
            "hotkeys": self._hotkeys.status(),
            "paused": self._translator.paused(),
            "llm_ready": bool(str(settings.get("translate_api_key") or "").strip()),
            "context_lines": int(settings.get("vntext_context_lines") or 4),
            "history": self._translator.history(10),
            # 每游戏专用钩子码（WillPlus 这类 Textractor 自带钩子搞不定的引擎）
            "hook_code": str(state.get("hook_code") or ""),
            "hook_auto": str(state.get("hook_auto") or ""),
            "game_hook": str((self._library.get(str(state.get("game_id") or "")) or {})
                             .get("vntext_hook") or ""),
            "game_locale": bool((self._library.get(str(state.get("game_id") or "")) or {})
                                .get("locale_enabled")),
        })
        return state

    def get_vntext_status(self) -> dict:
        return self._vntext_state()

    def set_vntext_hook(self, game_id: str, code: str) -> dict:
        """给单个游戏存一条专用 hook 码（空串 = 清除，回到自动）。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        text = " ".join(str(code or "").split())
        if text:
            if not vntext.looks_like_hook_code(text):
                return {"ok": False, "error": "bad-code",
                        "hint": "形如 HQ-4@A22E:AdvHD_crack.exe（H + 模式字母 + 偏移 @ 地址 : exe 名）"}
            if ":" not in text:
                # 只给了地址没给模块 → 用游戏自己的 exe 名补上
                text = f"{text}:{Path(str(game.get('exe') or '')).name}"
        self._library.update(game_id, vntext_hook=text)
        if self._vn_engine.status().get("running"):
            self._vn_engine.set_hook_code(text)
        return {"ok": True, "game_id": game_id, "vntext_hook": text,
                **self._vntext_state()}

    def set_vntext_option(self, key: str, value) -> dict:
        allowed = {"vntext_enabled": bool, "vntext_auto_start": bool,
                   "vntext_engine": str, "vntext_context_lines": int,
                   "vntext_max_chars": int, "vntext_ocr_interval": float}
        if key in allowed:
            if key == "vntext_engine" and str(value) not in ("auto", "hook", "ocr"):
                return {"ok": False, "error": "bad-engine"}
            cast = allowed[key]
            try:
                self._library.set_setting(key, cast(value))
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        elif key == "vntext_tractor_path":
            path = str(value or "").strip()
            if path and not Path(path).is_file():
                return {"ok": False, "error": "not-found"}
            self._library.set_setting(key, path)
        elif key == "vntext_overlay":
            patch = dict(self._library.settings.get("vntext_overlay") or {})
            patch.update(value if isinstance(value, dict) else {})
            self._library.set_setting(key, patch)
        else:
            return {"ok": False, "error": "bad-key"}
        return {"ok": True, **self._vntext_state()}

    def start_vntext(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        pid = int(self._pm.game_pid(game_id) or game.get("play_pid") or 0)
        if not pid:
            return {"ok": False, "error": "no-pid"}
        settings = self._library.settings
        region = game.get("vntext_ocr_region") or {}
        self._vn_engine.set_region(region)
        self._library.set_setting("vntext_enabled", True)
        state = self._vn_engine.start(game_id, pid,
                                      str(settings.get("vntext_engine") or "auto"),
                                      exe=str(game.get("exe") or ""),
                                      hook_code=str(game.get("vntext_hook") or ""))
        self._hotkeys.start()
        if state.get("running"):
            self._overlay.show()
            self._overlay.update({"reset": True, "status": "waiting",
                                  "lines": {"source": "", "translation": "",
                                            "status": "waiting"}})
            self._overlay.update({"status": "waiting",
                                  "notice": "" if settings.get("translate_api_key")
                                            else "没填 LLM Key：正在用免费接口，质量与速度较差"})
        default_bus().publish("vntext:status", self._vntext_state())
        return {"ok": bool(state.get("running")), **self._vntext_state()}

    def stop_vntext(self) -> dict:
        self._stop_hook_search() if self._stop_hook_search else None
        self._vn_engine.stop()
        self._overlay.update({"status": "idle"})
        self._overlay.hide()
        if self._library.settings.get("vntext_enabled"):
            self._library.set_setting("vntext_enabled", False)
        default_bus().publish("vntext:status", self._vntext_state())
        return {"ok": True, **self._vntext_state()}

    def close_overlay(self) -> dict:
        """主窗口关闭时把悬浮窗一起收掉。"""
        try:
            self._hotkeys.stop()
        except Exception:
            pass
        return self._overlay.close()

    def set_vntext_region(self, game_id: str, region: dict) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        clean = {
            "x": max(0.0, min(1.0, float((region or {}).get("x", 0.0)))),
            "y": max(0.0, min(1.0, float((region or {}).get("y", 0.62)))),
            "w": max(0.02, min(1.0, float((region or {}).get("w", 1.0)))),
            "h": max(0.02, min(1.0, float((region or {}).get("h", 0.34)))),
        }
        self._library.update(game_id, vntext_ocr_region=clean)
        self._vn_engine.set_region(clean)
        return {"ok": True, "region": clean}

    def capture_game_frame(self, game_id: str) -> dict:
        """截一张游戏窗口的图，供界面里框选 OCR 区域。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        pid = int(self._pm.game_pid(game_id) or game.get("play_pid") or 0)
        window = screencap.main_window(pid) if pid else None
        if not window:
            return {"ok": False, "error": "no-window"}
        shot = screencap.capture(window)
        if not shot.get("ok"):
            return {"ok": False, "error": shot.get("error") or "capture-failed"}
        name = f"vntext-{game_id}.png"
        target = config.USER_BG_DIR / name
        try:
            config.USER_BG_DIR.mkdir(parents=True, exist_ok=True)
            if not screencap.save_png(target, shot["bgr"], shot["width"], shot["height"]):
                return {"ok": False, "error": "no-pillow"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "url": f"userbg/{name}?v={int(time.time())}",
                "width": shot["width"], "height": shot["height"],
                "region": dict(game.get("vntext_ocr_region") or {})}

    def lock_vntext_thread(self, key: str) -> dict:
        self._vn_engine.lock_thread(key)
        return {"ok": True, **self._vntext_state()}

    def send_hook_code(self, code: str) -> dict:
        result = self._vn_engine.send_hook(code)
        return {**result, **self._vntext_state()}

    def translate_line_now(self, text: str) -> dict:
        text = str(text or "").strip()
        if not text:
            return {"ok": False, "error": "empty"}
        game_id = str(self._vn_engine.status().get("game_id") or "")
        self._overlay.show()
        self._translator.submit(text, game_id=game_id, source="manual")
        return {"ok": True}

    def set_vntext_paused(self, paused: bool) -> dict:
        self._translator.set_paused(bool(paused))
        self._overlay.update({"paused": self._translator.paused()})
        return {"ok": True, "paused": self._translator.paused()}

    def clear_vntext_context(self) -> dict:
        return self._translator.clear_context()

    def set_overlay_style(self, patch: dict) -> dict:
        return self._overlay.set_style(patch if isinstance(patch, dict) else {})

    def set_overlay_click_through(self, on: bool) -> dict:
        return self._overlay.set_click_through(bool(on))

    def toggle_overlay(self) -> dict:
        return self._toggle_overlay_visible()

    def list_glossary(self) -> dict:
        data = linetrans.load_glossary()
        return {"ok": True, "global": data.get("global") or {},
                "games": data.get("games") or {}}

    def set_glossary_entry(self, source: str, target: str, game_id: str = "") -> dict:
        source = str(source or "").strip()
        target = str(target or "").strip()
        if not source:
            return {"ok": False, "error": "empty-source"}
        data = linetrans.load_glossary()
        if game_id:
            bucket = data.setdefault("games", {}).setdefault(str(game_id), {})
        else:
            bucket = data.setdefault("global", {})
        if target:
            bucket[source] = target
        else:
            bucket.pop(source, None)
        data["version"] = int(data.get("version") or 1) + 1
        linetrans.save_glossary(data)
        return {"ok": True, **self.list_glossary()}

    def remove_glossary_entry(self, source: str, game_id: str = "") -> dict:
        return self.set_glossary_entry(source, "", game_id)

    def _on_vntext_line(self, payload: dict) -> None:
        text = str(payload.get("text") or "")
        game_id = str(payload.get("game_id") or "")
        self._translator.submit(text, game_id=game_id, source=str(payload.get("source") or ""))
        default_bus().publish("vntext:line", {"phase": "source", "text": text,
                                   "source": payload.get("source") or ""})

    def _on_translate_event(self, kind: str, payload: dict) -> None:
        text = str(payload.get("text") or "")
        if kind == "start":
            self._overlay.update({"lines": {"source": text, "translation": "",
                                            "status": "translating"}})
        elif kind == "delta":
            self._overlay.update({"lines": {"translation": payload.get("so_far") or "",
                                            "status": "translating"}})
        elif kind == "done":
            self._overlay.update({"lines": {"source": text,
                                            "translation": payload.get("translation") or "",
                                            "status": "done",
                                            "provider": payload.get("provider") or ""},
                                  "notice": ""})
            default_bus().publish("vntext:line", {"phase": "translated", "text": text,
                                       "translation": payload.get("translation") or "",
                                       "provider": payload.get("provider") or ""})
        elif kind == "error":
            # 失败时保留上一句译文，只提示一句，避免「真文本一闪而过」
            self._overlay.update({"status": "error",
                                  "notice": "这句没翻出来（可能是乱码或网络问题）"})
            default_bus().publish("vntext:line", {"phase": "error", "text": text,
                                       "error": payload.get("error") or ""})

    def _on_overlay_action(self, name: str, payload) -> dict:
        if name == "pause":
            return self.set_vntext_paused(bool(payload))
        if name == "hide":
            self._overlay.hide()
            return {"ok": True}
        if name == "retry":
            return self._translator.retranslate_last()
        if name == "clear_context":
            return self.clear_vntext_context()
        return {"ok": False, "error": "unknown-action"}

    def _toggle_overlay_click_through(self) -> None:
        result = self._overlay.toggle_click_through()
        default_bus().publish("vntext:status", {**self._vntext_state(), "toggled": result})

    def _toggle_overlay_visible(self) -> dict:
        if self._overlay.visible():
            self._overlay.hide()
        else:
            self._overlay.show()
        default_bus().publish("vntext:status", self._vntext_state())
        return {"ok": True, "visible": self._overlay.visible()}
