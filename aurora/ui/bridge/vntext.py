"""游戏内翻译与钩子查找桥接（P3.4 从 gl/api.py 原样搬出）。

覆盖翻译面板状态、钩子查找器、悬浮窗动作与术语表；方法体逐字未改。
"""
from __future__ import annotations


import json
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

import webview

from aurora.ui.bridge.shared import _public, _resolve_note
from gl import (config, detect, downloads, gameinput, hookfinder, hotkey, linetrans, locale,
                netproxy, ocr, overlay, process, screencap, steamlib, translate, vntext,
                winapi)   # TODO(P3.5): 逐个收口到 aurora.infra / aurora.platform
from gl.sources import SourceManager


class VnTextBridgeMixin:
    """翻译会话、钩子查找、悬浮窗与术语表。"""


    # ------------------------------------------------------------------ #
    # 游戏内翻译（Textractor 钩子 + 屏幕 OCR）
    # ------------------------------------------------------------------ #
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
        self._emit("vntext:status", self._vntext_state())
        return {"ok": bool(state.get("running")), **self._vntext_state()}


    def stop_vntext(self) -> dict:
        self.stop_hook_search()
        self._vn_engine.stop()
        self._overlay.update({"status": "idle"})
        self._overlay.hide()
        if self._library.settings.get("vntext_enabled"):
            self._library.set_setting("vntext_enabled", False)
        self._emit("vntext:status", self._vntext_state())
        return {"ok": True, **self._vntext_state()}


    # ------------------------------------------------------------------ #
    # 自研钩子查找器：OCR 取当前台词 → 内存定位 → 调试器 + 硬件断点 → 生成 H-code → 验证
    # ------------------------------------------------------------------ #
    def _hooksearch_state(self) -> dict:
        with self._hooksearch_lock:
            return dict(self._hooksearch)


    def _set_hooksearch(self, **patch) -> None:
        with self._hooksearch_lock:
            self._hooksearch.update(patch)
            state = dict(self._hooksearch)
        self._emit("hooksearch:status", state)


    def get_hook_search_status(self) -> dict:
        return {"ok": True, **self._hooksearch_state()}


    def advance_game(self, game_id: str) -> dict:
        """代点一下游戏（验证候选钩子码用，也是给用户的手动翻页按钮）。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        pid = int(self._vn_engine.status().get("pid")
                  or self._pm.game_pid(game_id) or 0)
        window = screencap.main_window(pid) if pid else None
        if not window:
            return {"ok": False, "error": "no-window"}
        how = self._hooksearch_advance(int(window["hwnd"]))
        return {"ok": bool(how), "how": how, "error": "" if how else "not-focused"}


    def _hooksearch_advance(self, hwnd: int) -> str:
        """先确保游戏在前台再点（否则 advance 会拒绝发送，游戏永远不会推进）。"""
        try:
            winapi.focus_window(int(hwnd))
            time.sleep(0.25)
        except Exception:
            pass
        return gameinput.advance(int(hwnd))


    def start_hook_search(self, game_id: str, text: str = "") -> dict:
        """开始一次查找（用户点按钮触发；同一时间只允许一个会话）。"""
        if self._hooksearch_thread and self._hooksearch_thread.is_alive():
            return {"ok": False, "error": "busy", **self._hooksearch_state()}
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        status = self._vn_engine.status()
        pid = int(status.get("pid") or self._pm.game_pid(game_id) or 0)
        if not status.get("running") or not pid:
            return {"ok": False, "error": "not-running",
                    "message": "先开启翻译（文本源要挂着才能验证候选码）"}
        window = screencap.main_window(pid)
        if not window:
            return {"ok": False, "error": "no-window", "message": "找不到游戏窗口"}
        self._hooksearch_stop.clear()
        self._set_hooksearch(phase="starting", message="准备中…", target=str(text or ""),
                             candidates=[], code="", error="", reason="", steps=0)
        self._hooksearch_thread = self._tasks.spawn(
            "vntext.hooksearch", self._hooksearch_worker, game_id, pid,
            int(window["hwnd"]), str(text or ""), thread_name="aurora-hooksearch")
        return {"ok": True, **self._hooksearch_state()}


    def stop_hook_search(self) -> dict:
        self._hooksearch_stop.set()
        thread = self._hooksearch_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        if self._hooksearch_state().get("phase") not in ("idle", "done", "error"):
            self._set_hooksearch(phase="idle", message="已中止")
        return {"ok": True, **self._hooksearch_state()}


    def _hooksearch_worker(self, game_id: str, pid: int, hwnd: int, text: str) -> None:
        target = " ".join(str(text or "").split())
        try:
            if not target:
                self._set_hooksearch(phase="ocr", message="正在识别画面上的当前台词…")
                shot = screencap.capture({"hwnd": hwnd}, self._vn_engine.status().get("region"))
                if shot.get("ok"):
                    result = ocr.recognize_bgr(shot["bgr"], shot["width"], shot["height"])
                    if result.get("ok"):
                        target = vntext.tidy_ocr_text(result["text"])
            if len(target) < 2:
                target = ""
            # ── 主路径：采样式收集（Misaka「翻页数次后列候选」的思路，不挂钩子）──
            #    采样所有线程栈 → 拿到「返回地址 + 槽偏移 + 那段文本」；
            #    文本能直接读到 → 和 OCR 到的当前台词一比，就知道哪条是原文。
            collected: list[dict] = []
            if True:
                self._set_hooksearch(
                    phase="collecting", target=target,
                    message="正在采样收集候选：Aurora 会翻几页，请别操作游戏")
                clicking = threading.Event()

                def click_loop() -> None:
                    while not clicking.is_set():
                        time.sleep(3.0)
                        if clicking.is_set():
                            break
                        self._hooksearch_advance(hwnd)

                clicker = self._tasks.spawn("vntext.hooksearch_advance", click_loop,
                                                 thread_name="aurora-hooksearch-advance")
                try:
                    collected = hookfinder.harvest(
                        pid, seconds=12.0, stop_event=self._hooksearch_stop,
                        on_progress=lambda found, samples: self._set_hooksearch(
                            message=f"已采样 {samples} 次、拿到 {found} 条候选…"))
                finally:
                    clicking.set()
                if self._hooksearch_stop.is_set():
                    return self._set_hooksearch(phase="idle", message="已中止")
                if collected:
                    scored = []
                    for row in collected:
                        score = 0.0
                        if target:
                            score = difflib.SequenceMatcher(
                                None, target, str(row.get("text") or "")).ratio()
                        scored.append((score, row))
                    scored.sort(key=lambda item: (-item[0], -item[1].get("count", 0)))
                    pool = [row for _score, row in scored[:12]]
                    self._set_hooksearch(
                        phase="verifying", steps=len(collected),
                        candidates=[{"code": "", "count": row.get("count", 0),
                                     "encoding": row.get("encoding"),
                                     "sample": str(row.get("text") or "")[:40],
                                     "verified": False} for row in pool],
                        message=f"采到 {len(collected)} 条候选，按「和当前台词像不像」排序…")
                    verified = self._hooksearch_verify_pool(game_id, pid, hwnd, pool,
                                                            target)
                    if verified:
                        return self._set_hooksearch(
                            phase="done", code=verified,
                            message=f"找到了：{verified}（已存为该游戏专用码）")
            # ── 兜底：断点法（差分定位缓冲区 + 硬件数据断点）──
            buffers: list[dict] = []
            if target:
                self._set_hooksearch(phase="scanning", target=target,
                                     message=f"先在内存里找这句文本：{target[:24]}")
                try:
                    # 精确扫描很快（~GB 级内存几秒）；模糊档很慢，留给差分法兜底
                    buffers = hookfinder.locate_buffers(pid, target, allow_fuzzy=False)
                except hookfinder.HookFinderError as exc:
                    if exc.reason == "no-access":
                        raise
                    buffers = []
            if not buffers:
                # 台词常常是渲染时临时生成的（内存里没有逐字副本）→ 改「盯变化」：
                # 拍一张内存哈希快照 → 翻一页 → 找变了的区域里新出现的台词
                self._set_hooksearch(
                    phase="collecting", buffers=0, target=target,
                    message="准备用差分法定位：马上会自动翻一页，请别操作游戏")
                before = hookfinder.snapshot(pid)
                for attempt in range(3):
                    if self._hooksearch_stop.is_set():
                        return self._set_hooksearch(phase="idle", message="已中止")
                    self._hooksearch_advance(hwnd)
                    self._set_hooksearch(
                        message=f"第 {attempt + 1} 次翻页后，正在比对内存变化…")
                    time.sleep(2.0)
                    buffers = hookfinder.changed_dialogues(pid, before)
                    if buffers:
                        target = target or str(buffers[0].get("text") or "")
                        break
                    before = hookfinder.snapshot(pid)
                if not buffers:
                    return self._hooksearch_fail(
                        "no-buffer", "翻页后没在内存里看到新台词 —— 确认游戏停在对话画面再试")
            self._set_hooksearch(
                phase="collecting", buffers=len(buffers),
                message="已布下断点，正在等你翻页（期间 Aurora 会自动帮你点几下）")
            clicking = threading.Event()

            def click_loop() -> None:
                while not clicking.is_set():
                    time.sleep(2.5)
                    if clicking.is_set():
                        break
                    self._hooksearch_advance(hwnd)

            clicker = self._tasks.spawn("vntext.hooksearch_advance", click_loop,
                                             thread_name="aurora-hooksearch-advance")
            found: dict = {"ok": False, "hits": [], "reason": "no-break"}
            try:
                # 每轮：先按「当前这句」重新定位一次（缓冲区可能换地址），再挂断点；
                # 一共给 3 轮机会，期间 Aurora 自己翻页制造访问。
                for round_no in range(3):
                    if self._hooksearch_stop.is_set():
                        break
                    if round_no and not buffers:
                        buffers = hookfinder.changed_dialogues(pid, before)
                    found = hookfinder.search(pid, buffers, seconds=6.0,
                                              stop_event=self._hooksearch_stop,
                                              on_hit=self._hooksearch_on_hit)
                    if found.get("ok"):
                        break
                    before = hookfinder.snapshot(pid)
                    self._hooksearch_advance(hwnd)
                    time.sleep(1.5)
                    fresh = hookfinder.changed_dialogues(pid, before)
                    if fresh:
                        buffers = fresh
                    if round_no < 2:
                        self._set_hooksearch(
                            message=f"第 {round_no + 2}/3 轮：重新定位当前台词后继续…")
            finally:
                clicking.set()
            if self._hooksearch_stop.is_set():
                return self._set_hooksearch(phase="idle", message="已中止")
            if not found.get("ok"):
                reason = str(found.get("reason") or "")
                if reason == "attach-failed":
                    return self._hooksearch_fail(
                        "attach-failed", "附加调试器失败（游戏可能在反调试/权限更高），改用 OCR 吧")
                if reason == "no-break":
                    return self._hooksearch_fail(
                        "no-break", "断点没被触发：确认台词确实推进过一次再试")
                return self._hooksearch_fail(
                    "no-hit", "抓到了访问，但栈上没留指针（这条文本只走寄存器），改用 OCR 吧")
            candidates: list[dict] = []
            for hit in found.get("hits", [])[:6]:
                module, base = hookfinder.module_of(pid, int(hit["rip"]))
                if not module:
                    continue
                try:
                    code = hookfinder.build_code(
                        module=module, module_base=base, rip=int(hit["rip"]),
                        offset=int(hit["offset"]), padding=int(hit["padding"]),
                        encoding=str(hit.get("encoding") or "utf-16"))
                except hookfinder.HookFinderError:
                    continue
                candidates.append({"code": code, "count": int(hit.get("count") or 0),
                                   "encoding": hit.get("encoding"), "verified": False})
            if not candidates:
                return self._hooksearch_fail("no-candidate", "候选都没落在模块里，改用 OCR 吧")
            self._set_hooksearch(phase="verifying", candidates=candidates,
                                 steps=int(found.get("steps") or 0),
                                 message=f"有 {len(candidates)} 个候选，逐个验证…")
            for index, row in enumerate(candidates):
                if self._hooksearch_stop.is_set():
                    return self._set_hooksearch(phase="idle", message="已中止")
                self._set_hooksearch(
                    message=f"正在验证第 {index + 1}/{len(candidates)} 个候选：{row['code']}")
                if self._hooksearch_try(game_id, hwnd, row["code"], target):
                    row["verified"] = True
                    self._set_hooksearch(phase="done", code=row["code"], candidates=candidates,
                                         message=f"找到了：{row['code']}（已存为该游戏专用码）")
                    return
            return self._hooksearch_fail("all-failed", "候选都验证失败，改用 OCR 吧")
        except hookfinder.HookFinderError as exc:
            return self._hooksearch_fail(exc.reason, exc.message)
        except Exception as exc:
            config.log(f"hooksearch failed: {exc}")
            return self._hooksearch_fail("error", f"查找出错：{exc}")


    def _hooksearch_on_hit(self, row: dict) -> None:
        self._set_hooksearch(message=f"已捕获访问（第 {row.get('count')} 次）：{hex(int(row.get('rip') or 0))}")


    def _hooksearch_verify_pool(self, game_id: str, pid: int, hwnd: int,
                                pool: list[dict], target: str) -> str:
        """把采样来的候选变成 H-code 逐个验证，返回第一个能出真台词的码。"""
        tried = 0
        for row in pool:
            if self._hooksearch_stop.is_set():
                return ""
            module, base = hookfinder.module_of(pid, int(row.get("rip") or 0))
            if not module:
                continue
            try:
                code = hookfinder.build_code(
                    module=module, module_base=base, rip=int(row["rip"]),
                    offset=int(row["offset"]), padding=int(row.get("padding") or 0),
                    encoding=str(row.get("encoding") or "utf-16"))
            except hookfinder.HookFinderError:
                continue
            tried += 1
            if tried > 8:
                break
            self._set_hooksearch(
                message=f"验证第 {tried} 个候选：{code}"
                        f"（采样到：{str(row.get('text') or '')[:20]}）")
            if self._hooksearch_try(game_id, hwnd, code, target):
                return code
        return ""


    def _hooksearch_fail(self, reason: str, message: str) -> None:
        config.log(f"hooksearch: {reason} {message}")
        self._set_hooksearch(phase="error", error=reason, reason=reason, message=message)


    def _hooksearch_try(self, game_id: str, hwnd: int, code: str, target: str) -> bool:
        """发一条候选码 → 代点翻页 → 看这条线程有没有吐出像样的台词。"""
        before = self._hooksearch_sample(code)
        if not self._vn_engine.send_hook(code).get("ok"):
            return False
        for _ in range(3):
            if self._hooksearch_stop.is_set():
                return False
            self._hooksearch_advance(hwnd)
            deadline = time.time() + 5.0
            while time.time() < deadline and not self._hooksearch_stop.is_set():
                time.sleep(0.4)
                sample = self._hooksearch_sample(code)
                if sample and sample != before:
                    if vntext.looks_like_dialogue(sample) or \
                            difflib.SequenceMatcher(None, target, sample).ratio() >= 0.6:
                        self._library.update(game_id, vntext_hook=code)
                        self._vn_engine.set_hook_code(code)
                        return True
        return False


    def _hooksearch_sample(self, code: str) -> str:
        status = self._vn_engine.status()
        for row in status.get("threads") or []:
            if vntext.hook_code_matches(code, f"{row.get('name','')}:{row.get('code','')}"):
                return str(row.get("sample") or "")
        return ""


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


    # ------------------------------------------------------------------ #
    def _on_vntext_line(self, payload: dict) -> None:
        text = str(payload.get("text") or "")
        game_id = str(payload.get("game_id") or "")
        self._translator.submit(text, game_id=game_id, source=str(payload.get("source") or ""))
        self._emit("vntext:line", {"phase": "source", "text": text,
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
            self._emit("vntext:line", {"phase": "translated", "text": text,
                                       "translation": payload.get("translation") or "",
                                       "provider": payload.get("provider") or ""})
        elif kind == "error":
            # 失败时保留上一句译文，只提示一句，避免「真文本一闪而过」
            self._overlay.update({"status": "error",
                                  "notice": "这句没翻出来（可能是乱码或网络问题）"})
            self._emit("vntext:line", {"phase": "error", "text": text,
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
        self._emit("vntext:status", {**self._vntext_state(), "toggled": result})


    def _toggle_overlay_visible(self) -> dict:
        if self._overlay.visible():
            self._overlay.hide()
        else:
            self._overlay.show()
        self._emit("vntext:status", self._vntext_state())
        return {"ok": True, "visible": self._overlay.visible()}
