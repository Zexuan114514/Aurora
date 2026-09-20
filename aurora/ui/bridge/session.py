"""启动 / 会话 / 下载扫描桥接（P3.5 从 gl/api.py 原样搬出）。

覆盖：启动（含转区命令拼装）、进程树回调、会话结算与崩溃恢复、心跳、结束游戏、下载目录扫描。
方法体逐字未改；`gl` 依赖在 P3.6 收口到 aurora.infra / aurora.platform。
"""
from __future__ import annotations

import time
from pathlib import Path

from aurora.domain import session_rules
from aurora.ui.bridge.shared import _public
from gl import config, locale, process   # TODO(P3.6): 收口


class SessionBridgeMixin:
    """启动与结束游戏、会话记账与恢复、下载目录扫描。"""


    def scan_downloads(self) -> dict:
        """手动扫一遍下载目录（忽略“已处理”记录）。"""
        res = self._downloads.scan_now()
        if res.get("handled"):
            self._emit("downloads:status", {
                "kind": "imported", "names": res["handled"][:6],
                "count": res.get("imported") or 0,
            })
        return {"ok": bool(res.get("ok")), **res}


    def set_game_locale(self, game_id: str, enabled: bool, guid: str = "") -> dict:
        """单个游戏的转区开关与配置。"""
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        updated = self._library.update(game_id, locale_enabled=bool(enabled),
                                       locale_guid=str(guid or "").strip())
        if updated:
            self._emit("game:updated", _public(updated, self._pm))
        return {"ok": bool(updated), "game": _public(updated, self._pm) if updated else None}


    # ------------------------------------------------------------------ #
    # 运行
    # ------------------------------------------------------------------ #
    def launch(self, game_id: str) -> dict:
        game = self._library.get(game_id)
        if not game:
            return {"ok": False, "error": "no-game"}
        launcher, locale_note = self._locale_command(game)
        result = self._pm.start(game, launcher=launcher)
        if result.get("ok"):
            now = int(time.time())
            self._library.touch_played(game_id)
            # 落盘会话标记：万一启动器先被关掉，下次启动还能把时长补回来
            self._library.update(
                game_id,
                play_started_at=int(result.get("started_at") or now),
                play_pid=int(result.get("pid") or 0),
                play_launcher_pid=int(result.get("pid") or 0),
                play_heartbeat=now,
                play_count=int(game.get("play_count") or 0) + 1,
            )
            self._start_heartbeat()
            self._emit("game:running", {"id": game_id, "pid": result.get("pid"),
                                        "locale": locale_note})
        return result


    def _locale_command(self, game: dict) -> tuple[list[str] | None, str]:
        """按游戏的转区设置决定启动方式；返回 (启动命令, 说明)。"""
        if not game.get("locale_enabled"):
            return None, ""
        proc = locale.detect(str(self._library.settings.get("le_proc_path") or ""))
        if not proc:
            return None, "no-le"
        exe = str(game.get("exe") or "")
        if Path(exe).suffix.lower() != ".exe":
            return None, "unsupported-target"
        guid = str(game.get("locale_guid") or "").strip()
        return locale.build_command(proc, exe, guid=guid), ("locale" if guid else "locale-default")


    def _on_game_found(self, game_id: str, pid: int) -> None:
        """找到游戏本体进程：把它记下来，启动器重启后也能重新接管。"""
        if not game_id or not pid:
            return
        self._library.update(game_id, play_pid=int(pid))
        # 开了「启动游戏自动翻译」就顺手接上文本源
        settings = self._library.settings
        if settings.get("vntext_auto_start") or settings.get("vntext_enabled"):
            try:
                self.start_vntext(game_id)
            except Exception as exc:
                config.log(f"vntext auto start failed: {exc}")


    def _on_game_exit(self, game_id: str, seconds: float) -> None:
        """会话结束：结算时长、记一条会话历史、清掉会话标记。"""
        try:
            if self._vn_engine.status().get("game_id") == game_id:
                self.stop_vntext()
        except Exception as exc:
            config.log(f"vntext auto stop failed: {exc}")
        game = self._library.get(game_id)
        if not game:
            return
        now = int(time.time())
        started = int(game.get("play_started_at") or 0) or int(now - seconds)
        self._library.update(
            game_id,
            play_started_at=0, play_pid=0, play_launcher_pid=0, play_heartbeat=0,
        )
        # 会话历史：内存保留最近 50 条 + 追加进 state/sessions.jsonl（立即落盘）
        self._library.record_session(game_id, {"ts_start": started, "ts_end": now,
                                               "seconds": int(seconds), "source": "session"})
        self._library.touch_played(game_id, seconds)
        updated = self._library.get(game_id)
        if updated:
            self._emit("game:stopped", _public(updated, self._pm))


    def stop(self, game_id: str) -> dict:
        result = self._pm.stop(game_id)
        game = self._library.get(game_id)
        if game:
            self._emit("game:updated", _public(game, self._pm))
        return result


    def _start_heartbeat(self) -> None:
        if self._heartbeat is not None and self._heartbeat.is_alive():
            return

        def loop() -> None:
            while True:
                time.sleep(self.HEARTBEAT_SECONDS)
                try:
                    self._beat()
                except Exception:
                    pass

        thread = threading.Thread(target=loop, daemon=True, name="aurora-heartbeat")
        self._heartbeat = thread
        thread.start()


    def _beat(self) -> None:
        now = int(time.time())
        for game_id in self._pm.running_ids():
            self._library.update(game_id, play_heartbeat=now)


    def _recover_sessions(self) -> None:
        """启动时对账上次没结束的会话。

        游戏还在跑就重新接管（界面照常显示「运行中」、退出时照常累计），
        已经结束的按最后一个心跳补记时长，避免「先关启动器再关游戏」丢时长。
        """
        now = int(time.time())
        for game in self._library.all():
            started = int(game.get("play_started_at") or 0)
            if started <= 0:
                continue
            if self._pm.attach(game, started):
                # 接管后由 ProcessManager 自己的监控线程负责判定结束并回调
                # _on_game_exit（旧实现这里调用已删除的 self._watch，会启动即崩）
                config.log(f"reattached running game {game['id']} pid={game.get('play_pid')}")
                self._start_heartbeat()
                continue
            seconds = session_rules.recovered_seconds(
                started_at=started, heartbeat=game.get("play_heartbeat") or 0, now=now)
            self._library.update(game["id"], play_started_at=0, play_pid=0,
                                 play_launcher_pid=0, play_heartbeat=0)
            if session_rules.is_countable(seconds, self.HEARTBEAT_SECONDS):
                self._library.touch_played(game["id"], seconds)
                config.log(f"recovered {seconds}s playtime for {game['id']}")
