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
from aurora.platform import gameinput, hookfinder, ocr, screencap, winapi
from gl import config, vntext   # TODO(P3.10): config 收口到 aurora.infra


class HookSearchService:
    """钩子查找：会话状态、采样、试码、失败路径。"""

    #: 签名播种阶段最多花多久（超了就往下走老路子，别让界面干等）
    SEED_BUDGET = 60.0
    #: 一个函数入口最多试几个偏移（每个偏移都要发一条钩子码 + 代点一次）
    SEED_OFFSETS = 12
    #: 最多看几个签名命中的函数
    SEED_FUNCTIONS = 4

    #: Textractor 的伪线程：剪贴板/控制台里的内容不是游戏文本，验证时要跳过
    PSEUDO_THREADS = ("剪贴板", "控制台", "默认")

    def __init__(self, library, pm, engine, tasks, overlay=None) -> None:
        self._library = library
        self._pm = pm
        self._vn_engine = engine
        self._tasks = tasks
        self._overlay = overlay
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
        # 抢前台要重试：Windows 允许「刚被别的窗口抢走」的前台锁，而且真机实测
        # 第一次 focus_window 常常不生效（返回 False 但窗口其实已经在上层）。
        for attempt in range(3):
            try:
                winapi.focus_window(int(hwnd))
                time.sleep(0.25)
            except Exception:
                pass
            sent = gameinput.advance(int(hwnd))
            if sent:
                return sent
            fresh = self._game_window(game_id) if game_id else None
            if fresh and int(fresh["hwnd"]) != int(hwnd or 0):
                hwnd = int(fresh["hwnd"])
            time.sleep(0.2 * (attempt + 1))
        return ""

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
            # ── 主路径 0：签名播种（最快、命中率最高）──
            #    采样式收集对「自绘文字」引擎是没用的：文本指针只在绘制那一瞬间存在，
            #    采样永远撞不上（アマカノ３ 实测 1200+ 条候选全是噪声）。真正管用的是
            #    MisakaHookFinder / Textractor「Search for hooks」那套：
            #    先用特征码定位绘制函数 → 再在函数入口按固定顺序试数据偏移。
            # 先把可能拖慢游戏的用户码摘掉，再开始试码（见 _hooksearch_clean_session）
            previous_code = self._hooksearch_clean_session()
            seeded = self._hooksearch_seed_pass(game_id, pid, hwnd, target)
            self._hooksearch_restore_session(previous_code, seeded)
            if seeded:
                return self._set_hooksearch(
                    phase="done", code=seeded,
                    message=f"找到了：{seeded}（已存为该游戏专用码）")
            if self._hooksearch_stop.is_set():
                return self._set_hooksearch(phase="idle", message="已中止")
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
                            "no-text",
                            "采样阶段未找到可验证的台词候选（不代表整次侦测失败）；"
                            "现有钩子 / 缺字补全仍会继续监听")
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

    # ------------------------------------------------------------------ #
    # 签名播种：特征码定位绘制函数 → 逐个试寄存器/栈偏移
    # ------------------------------------------------------------------ #
    def _hooksearch_seed_pass(self, game_id: str, pid: int, hwnd: int,
                              target: str) -> str:
        """按「文本绘制函数」的序言特征码找候选点，逐个试码，返回第一条能出台词的码。

        思路来自 MisakaHookFinder / Textractor 的 SearchForHooks：先找嫌疑函数，
        再在函数入口试「数据偏移」。x64 上偏移主要是**寄存器**（Textractor 的存根
        会把 16 个寄存器压在挂钩点 RSP 下方，H-code 写负数偏移就能取到）。
        """
        started = time.time()
        self._set_hooksearch(phase="seeding",
                             message="正在按引擎特征码找可疑的文本绘制函数…")
        try:
            seats = hookfinder.scan_text_signatures(pid, limit=self.SEED_FUNCTIONS)
        except Exception as exc:
            config.log(f"hooksearch: 签名扫描失败 {exc}")
            seats = []
        if not seats:
            config.log("hooksearch: 签名播种没找到候选函数")
            return ""
        tried = 0
        fallback = ""                      # 只「偶尔」吐过台词的码，全试完再兜底
        stop_overlay = self._hooksearch_overlay_off()
        try:
            for row in seats:
                if self._hooksearch_stop.is_set():
                    return ""
                module = str(row.get("module") or "")
                base = int(row.get("base") or 0)
                address = int(row.get("address") or 0)
                if not module or not base or not address:
                    continue
                offsets = list(hookfinder.HOOK_OFFSETS)[:self.SEED_OFFSETS]
                for index, offset in enumerate(offsets):
                    if self._hooksearch_stop.is_set():
                        return ""
                    if time.time() - started > self.SEED_BUDGET:
                        config.log("hooksearch: 签名播种超时，转老路子")
                        return ""
                    try:
                        code = hookfinder.build_code(
                            module=module, module_base=base, rip=address,
                            offset=int(offset), encoding="utf-8")
                    except hookfinder.HookFinderError:
                        continue
                    tried += 1
                    self._set_hooksearch(
                        phase="verifying", steps=tried,
                        message=f"试第 {tried} 个候选：{module}+{address - base:#X} "
                                f"偏移 {offset:#x}（{code}）")
                    config.log(f"hooksearch: 试第 {tried} 个候选 {code}")
                    if self._hooksearch_try(game_id, hwnd, code, target,
                                            clicks=2, wait=3.0):
                        if self._hooksearch_confirm(game_id, hwnd, code, target):
                            return code
                        if not fallback:
                            fallback = code      # 偶尔能用也先记着，全试完再兜底
                # UTF-16 引擎的兜底：同一条函数只再试最像的几个偏移
                for offset in offsets[:4]:
                    if self._hooksearch_stop.is_set():
                        return ""
                    if time.time() - started > self.SEED_BUDGET:
                        config.log("hooksearch: 签名播种超时（UTF-16 阶段），转老路子")
                        return ""
                    try:
                        code = hookfinder.build_code(
                            module=module, module_base=base, rip=address,
                            offset=int(offset), encoding="utf-16")
                    except hookfinder.HookFinderError:
                        continue
                    tried += 1
                    self._set_hooksearch(
                        phase="verifying", steps=tried,
                        message=f"试第 {tried} 个候选（UTF-16）：{code}")
                    config.log(f"hooksearch: 试第 {tried} 个候选(UTF-16) {code}")
                    if self._hooksearch_try(game_id, hwnd, code, target,
                                            clicks=1, wait=3.0):
                        if self._hooksearch_confirm(game_id, hwnd, code, target):
                            return code
                        if not fallback:
                            fallback = code
        finally:
            self._hooksearch_overlay_restore(stop_overlay)
        if fallback:
            config.log(f"hooksearch: 没有稳定命中的，退回偶尔能用的 {fallback}")
            return fallback
        config.log(f"hooksearch: 签名播种试了 {tried} 条候选码，都没吐出台词")
        return ""

    def _hooksearch_overlay_off(self):
        """找钩子期间把悬浮窗设成穿透——否则置顶的悬浮窗会挡住代点的位置。

        返回原来的 click_through 值（找不到悬浮窗时返回 None）。
        """
        overlay = self._overlay
        if overlay is None:
            return None
        current = None
        try:
            current = bool(overlay.click_through)
        except Exception:
            try:
                current = bool(overlay.initial_payload().get("click_through"))
            except Exception:
                current = None
        if current:
            return current                    # 本来就穿透，不用动
        try:
            overlay.set_click_through(True, persist=False)
            config.log("hooksearch: 悬浮窗临时改为穿透")
        except Exception as exc:
            config.log(f"hooksearch: 关不掉悬浮窗穿透 {exc}")
        return current

    def _hooksearch_overlay_restore(self, previous) -> None:
        if previous is None or self._overlay is None:
            return
        try:
            self._overlay.set_click_through(bool(previous), persist=False)
            config.log("hooksearch: 悬浮窗穿透设置已还原")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 干净会话：找钩子前把「用户/实测带出的码」摘掉
    # ------------------------------------------------------------------ #
    def _hooksearch_clean_session(self) -> str:
        """找钩子期间把引擎切到「不带任何用户码」的会话，返回原来的码（没有返回 ""）。

        真机教训（アマカノ３，20:47 那次全失败）：库里那条 `HS65001#20@38A78`
        挂在**绘制热函数**上（每帧被调上千次），Textractor 每次调用都要走一遍
        Send —— 游戏被拖慢十几倍，我们的「代点一次 + 等 3 秒」根本等不到新台词渲染，
        12 个偏移全被误判成失败。先把码摘掉，进程恢复原速，验证才准。

        找不到游戏 exe / 引擎没在跑就什么都不做（返回 ""）。
        """
        state = self._vn_engine.status()
        previous = str(state.get("hook_code") or "")
        if not previous or not state.get("running"):
            return ""
        game_id = str(state.get("game_id") or "")
        pid = int(state.get("pid") or 0)
        game = self._library.get(game_id) if game_id else None
        exe = str((game or {}).get("exe") or "")
        if not pid or not exe:
            return ""
        try:
            self._vn_engine.stop()
            time.sleep(0.6)
            self._vn_engine.start(game_id, pid, mode="hook", exe=exe, hook_code="")
            config.log(f"hooksearch: 已切到干净会话（临时摘掉 {previous}）")
        except Exception as exc:
            config.log(f"hooksearch: 干净会话切换失败 {exc}")
            return ""
        return previous

    def _hooksearch_restore_session(self, previous: str, found: str) -> None:
        """没找到新码就把原来那条还回去（找到了的话 `_hooksearch_try` 已经写进去了）。"""
        if not previous or found:
            return
        try:
            self._vn_engine.set_hook_code(previous)
            config.log(f"hooksearch: 没找到新码，已还原 {previous}")
        except Exception:
            pass

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
        # 这是某个阶段的结果，不应覆盖引擎已经在跑的监听会话。面板会继续从
        # vntext:status 接收有效线程；因此这里保留 warning 语义，避免把
        # “采样法失败”误报成“找钩子整体失败”。
        phase = "warning" if reason == "no-text" else "error"
        self._set_hooksearch(phase=phase, error=reason, reason=reason, message=message)

    def _hooksearch_try(self, game_id: str, hwnd: int, code: str, target: str, *,
                        clicks: int = 3, wait: float = 5.0) -> bool:
        """发一条候选码 → 代点翻页 → 看这条线程有没有吐出像样的台词。

        clicks/wait 给签名播种用更小的值（那边候选多，每条只给一次机会）。
        """
        before = self._hooksearch_sample(code)
        if not self._vn_engine.send_hook(code).get("ok"):
            return False
        seen = ""
        for _ in range(max(1, int(clicks))):
            if self._hooksearch_stop.is_set():
                return False
            self._hooksearch_advance(hwnd, game_id)
            deadline = time.time() + max(0.5, float(wait))
            while time.time() < deadline and not self._hooksearch_stop.is_set():
                time.sleep(0.4)
                sample = self._hooksearch_sample(code)
                if sample and sample != before:
                    if len(sample) > len(seen):
                        seen = sample
                    if vntext.looks_like_dialogue(sample) \
                            or hook_candidate_score(sample) >= 0.5 or \
                            difflib.SequenceMatcher(None, target, sample).ratio() >= 0.6:
                        config.log(f"hooksearch: 命中 {code} → {sample[:40]!r}")
                        self._library.update(game_id, vntext_hook=code)
                        self._vn_engine.set_hook_code(code)
                        return True
        # 失败也留一行现场：知道它到底吐了什么，才能判断是偏移不对还是读到了垃圾
        config.log(f"hooksearch: 候选没通过 {code} → {seen[:40]!r}" if seen
                   else f"hooksearch: 候选没吐出东西 {code}")
        return False

    def _hooksearch_confirm(self, game_id: str, hwnd: int, code: str, target: str) -> bool:
        """候选已经吐过一句，再点两下确认它**稳定**出文本。

        真机教训（アマカノ３）：同一个绘制函数被不同调用路径调用时，文本指针待的
        寄存器不一样（这条场景走 RDX，主story 走 R12）。只看一次命中就落库，可能
        存下「只有某些场景能用」的码；再过一轮能显著提高存下来的码的覆盖面。
        """
        hits = 0
        before = self._hooksearch_sample(code)
        for _ in range(2):
            if self._hooksearch_stop.is_set():
                break
            self._hooksearch_advance(hwnd, game_id)
            deadline = time.time() + 3.5
            while time.time() < deadline and not self._hooksearch_stop.is_set():
                time.sleep(0.4)
                sample = self._hooksearch_sample(code)
                if sample and sample != before:
                    before = sample
                    if vntext.looks_like_dialogue(sample) \
                            or hook_candidate_score(sample) >= 0.5 or \
                            difflib.SequenceMatcher(None, target, sample).ratio() >= 0.6:
                        hits += 1
                    break
        config.log(f"hooksearch: 确认轮 {code} → 命中 {hits}/2")
        return hits >= 1

    def _hooksearch_sample(self, code: str) -> str:
        """取「我们这条钩子码」的线程样例。

        走引擎的 `hook_sample_for`：它扫**全量**线程表。之前这里翻的是
        `status()["threads"]`（只留前 12 条的界面投影），游戏里一旦有别的钩子在
        刷屏，候选线程就被挤出前 12，验证必然失败（アマカノ３ 真机踩过）。
        伪线程（剪贴板/控制台/默认）由引擎侧过滤。
        """
        reader = getattr(self._vn_engine, "hook_sample_for", None)
        if callable(reader):
            return str(reader(code) or "")
        return ""            # 老引擎没有这个接口（理论上不会走到）
