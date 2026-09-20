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
        return self._vntext._vntext_state()


    def get_vntext_status(self) -> dict:
        return self._vntext.get_vntext_status()


    def set_vntext_hook(self, game_id: str, code: str) -> dict:
        return self._vntext.set_vntext_hook(game_id, code)


    def set_vntext_option(self, key: str, value) -> dict:
        return self._vntext.set_vntext_option(key, value)


    def start_vntext(self, game_id: str) -> dict:
        return self._vntext.start_vntext(game_id)


    def stop_vntext(self) -> dict:
        return self._vntext.stop_vntext()


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
        return self._vntext.close_overlay()


    def set_vntext_region(self, game_id: str, region: dict) -> dict:
        return self._vntext.set_vntext_region(game_id, region)


    def capture_game_frame(self, game_id: str) -> dict:
        return self._vntext.capture_game_frame(game_id)


    def lock_vntext_thread(self, key: str) -> dict:
        return self._vntext.lock_vntext_thread(key)


    def send_hook_code(self, code: str) -> dict:
        return self._vntext.send_hook_code(code)


    def translate_line_now(self, text: str) -> dict:
        return self._vntext.translate_line_now(text)


    def set_vntext_paused(self, paused: bool) -> dict:
        return self._vntext.set_vntext_paused(paused)


    def clear_vntext_context(self) -> dict:
        return self._vntext.clear_vntext_context()


    def set_overlay_style(self, patch: dict) -> dict:
        return self._vntext.set_overlay_style(patch)


    def set_overlay_click_through(self, on: bool) -> dict:
        return self._vntext.set_overlay_click_through(on)


    def toggle_overlay(self) -> dict:
        return self._vntext.toggle_overlay()


    def list_glossary(self) -> dict:
        return self._vntext.list_glossary()


    def set_glossary_entry(self, source: str, target: str, game_id: str='') -> dict:
        return self._vntext.set_glossary_entry(source, target, game_id)


    def remove_glossary_entry(self, source: str, game_id: str='') -> dict:
        return self._vntext.remove_glossary_entry(source, game_id)


    # ------------------------------------------------------------------ #
    def _on_vntext_line(self, payload: dict) -> None:
        return self._vntext._on_vntext_line(payload)


    def _on_translate_event(self, kind: str, payload: dict) -> None:
        return self._vntext._on_translate_event(kind, payload)


    def _on_overlay_action(self, name: str, payload) -> dict:
        return self._vntext._on_overlay_action(name, payload)


    def _toggle_overlay_click_through(self) -> None:
        return self._vntext._toggle_overlay_click_through()


    def _toggle_overlay_visible(self) -> dict:
        return self._vntext._toggle_overlay_visible()
