"""钩子查找器用例服务（P3.8-g）：采样线程栈收集候选 → 逐条试码 → 回显判定。

从 aurora/ui/bridge/vntext.py 原样搬出；会话状态（候选列表 / 停止事件 / 线程）随服务走。
只在用户手动触发时运行，属于高风险链路（调试器 + 硬件断点）。
"""
from __future__ import annotations

import difflib

import threading
import time
from pathlib import Path

from aurora.app.events import default_bus
from aurora.domain.text_rules import hook_candidate_score
from gl import (config, gameinput, hookfinder, ocr, screencap, vntext,
                winapi)   # TODO(P3.8): 收口到 aurora.platform / aurora.infra


class HookSearchService:
    """钩子查找：会话状态、采样、试码、失败路径。"""

    def __init__(self, library, pm, engine, tasks) -> None:
        self._library = library
        self._pm = pm
        self._vn_engine = engine
        self._tasks = tasks
        self._hooksearch: dict = {"phase": "idle", "message": "", "target": "",
                                  "candidates": [], "code": "", "error": "",
                                  "reason": "", "steps": 0}
        self._hooksearch_stop = threading.Event()
        self._hooksearch_thread = None
        self._hooksearch_lock = threading.RLock()

    def _hooksearch_state(self) -> dict:
        with self._hooksearch_lock:
            return dict(self._hooksearch)

    def _set_hooksearch(self, **patch) -> None:
        with self._hooksearch_lock:
            self._hooksearch.update(patch)
            state = dict(self._hooksearch)
        default_bus().publish("hooksearch:status", state)

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

    def _hooksearch_advance(self, hwnd: int, game_id: str = "") -> str:
        """先确保游戏在前台再点（窗口失效时先重新解析，避免点进已销毁的句柄）。"""
        if game_id:
            fresh = self._game_window(game_id)
            if fresh and int(fresh["hwnd"]) != int(hwnd or 0):
                config.log(f"hooksearch: window changed {hwnd} -> {fresh['hwnd']}")
                hwnd = int(fresh["hwnd"])
        try:
            winapi.focus_window(int(hwnd))
            time.sleep(0.25)
        except Exception:
            pass
        sent = gameinput.advance(int(hwnd))
        if not sent and game_id:
            fresh = self._game_window(game_id)
            if fresh and int(fresh["hwnd"]) != int(hwnd or 0):
                winapi.focus_window(int(fresh["hwnd"]))
                time.sleep(0.25)
                sent = gameinput.advance(int(fresh["hwnd"]))
        return sent

    def _game_window(self, game_id: str) -> dict | None:
        """按游戏进程重新解析主窗口。

        实测教训（アマカノ３）：会话开始时拿到的 hwnd 可能在游戏换模式/重启后失效，
        继续用它点击＝点进已销毁的窗口，台词不推进 → 硬件断点永远不触发。
        """
        pid = int(self._vn_engine.status().get("pid") or self._pm.game_pid(game_id) or 0)
        if not pid:
            return None
        try:
            return screencap.main_window(pid)
        except Exception:
            return None

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
                fresh = self._game_window(game_id)
                use_hwnd = int(fresh["hwnd"]) if fresh else hwnd
                shot = screencap.capture({"hwnd": use_hwnd}, self._vn_engine.status().get("region"))
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
                        self._hooksearch_advance(hwnd, game_id)

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
                    # 先按「文本像不像台词」打分（OCR 只占 0.25 权重），再按采样次数
                    scored = sorted(
                        ((hook_candidate_score(str(row.get("text") or ""),
                                                     ocr_target=target,
                                                     count=int(row.get("count") or 0)), row)
                         for row in collected),
                        key=lambda item: (-item[0], -item[1].get("count", 0)))
                    pool = [row for score, row in scored[:12] if score > 0]
                    if not pool:
                        return self._hooksearch_fail(
                            "no-text", "采样到的候选都不像台词（可能停在菜单/黑屏），翻到正文再试")
                    self._set_hooksearch(
                        phase="verifying", steps=len(collected),
                        candidates=[{"code": "", "count": row.get("count", 0),
                                     "encoding": row.get("encoding"),
                                     "sample": str(row.get("text") or "")[:40],
                                     "score": hook_candidate_score(
                                         str(row.get("text") or ""), ocr_target=target,
                                         count=int(row.get("count") or 0)),
                                     "verified": False} for row in pool],
                        message=f"采到 {len(collected)} 条候选，按「像不像台词（OCR 仅参考）」排序…")
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
                    self._hooksearch_advance(hwnd, game_id)
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
                    self._hooksearch_advance(hwnd, game_id)

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
                    self._hooksearch_advance(hwnd, game_id)
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
            # 实测教训（アマカノ３ / Artemis-Emote）：这类引擎的自绘文字是 UTF-8，
            # 只按 UTF-16 建码会读到乱码 → 候选全判失败。同一地址两种编码都试一遍。
            encodings = [str(row.get("encoding") or "utf-16")]
            for alt in ("utf-8", "utf-16"):
                if alt not in encodings:
                    encodings.append(alt)
            codes = []
            for enc in encodings:
                try:
                    codes.append(hookfinder.build_code(
                        module=module, module_base=base, rip=int(row["rip"]),
                        offset=int(row["offset"]), padding=int(row.get("padding") or 0),
                        encoding=enc))
                except hookfinder.HookFinderError:
                    continue
            if not codes:
                continue
            tried += 1
            if tried > 8:
                break
            self._set_hooksearch(
                message=f"验证第 {tried} 个候选：{codes[0]}"
                        f"（采样到：{str(row.get('text') or '')[:20]}）")
            for code in codes:          # 先 utf-8 再 utf-16，命中即返回
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
            self._hooksearch_advance(hwnd, game_id)
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
