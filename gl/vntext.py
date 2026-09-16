"""游戏内文本来源：TextractorCLI 文本钩子 + 屏幕 OCR 兜底。

TextractorCLI 的契约（读它的 host/CLI/main.cpp 得出）：
  stdin  ：UTF-16LE 命令，`attach -P<pid>` / `detach -P<pid>` / `<hook码> -P<pid>`
  stdout ：UTF-16LE 行，格式 `[handle:pid:addr:ctx:ctx2:线程名:hook码] 正文`
我们只运行用户自己安装的 TextractorCLI.exe，不打包、不修改它。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config, screencap

CREATE_NO_WINDOW = 0x08000000
CLI_NAME = "TextractorCLI.exe"
TEXTRACTOR_URL = "https://github.com/Artikash/Textractor/releases"

#: 钩子文本里常见的菜单/系统提示，翻译它们只会干扰阅读
NOISE_WORDS = ("設定", "セーブ", "ロード", "タイトル", "終了", "バックログ", "スキップ",
               "オプション", "コンフィグ", "ウィンドウ", "フルスクリーン", "音量", "戻る",
               "はじめから", "つづきから", "終わります", "よろしいですか")

LINE_RE = re.compile(
    r"^\[([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+):"
    r"([^\]]*):([^\]]*)\]\s?(.*)$")


def candidate_dirs() -> list[Path]:
    """常见安装位置：环境变量目录 + 各盘常见路径 + PATH。"""
    out: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        root = os.environ.get(env_name)
        if root:
            out += [Path(root) / "Textractor", Path(root) / "Textractor" / "x64",
                    Path(root) / "Downloads" / "Textractor", Path(root) / "Desktop" / "Textractor"]
    for drive in "CDEFGH":
        base = Path(f"{drive}:\\")
        try:
            if not base.exists():
                continue
        except OSError:
            continue
        out += [base / "Textractor", base / "Textractor" / "x64",
                base / "Tools" / "Textractor", base / "Tools" / "Textractor" / "x64",
                base / "Program Files" / "Textractor"]
    found = shutil.which("TextractorCLI") or shutil.which(CLI_NAME)
    if found:
        out.insert(0, Path(found))
    return out


def find_cli(saved: str = "") -> str:
    """返回可用的 TextractorCLI.exe；找不到返回空串。"""
    if saved:
        path = Path(saved)
        if path.is_dir():
            path = path / CLI_NAME
        if path.is_file():
            return str(path)
    for item in candidate_dirs():
        path = item if item.suffix.lower() == ".exe" else item / CLI_NAME
        if path.is_file():
            return str(path)
    return ""


def parse_hook_line(raw: str) -> dict | None:
    """解析 TextractorCLI 的一行，拿不到正文就返回 None。"""
    if not raw:
        return None
    match = LINE_RE.match(raw.rstrip("\r\n"))
    if not match:
        text = raw.strip()
        return {"text": text, "thread": "", "name": "", "code": ""} if text else None
    handle, pid, addr, ctx, ctx2, name, code, text = match.groups()
    text = text.strip()
    if not text:
        return None
    return {"text": text, "thread": f"{handle}:{pid}:{addr}:{ctx}:{ctx2}",
            "name": name, "code": code}


def looks_like_noise(text: str, max_chars: int = 1200) -> bool:
    """过滤纯数字/符号、过短、系统菜单这类不该翻的行。"""
    body = text.strip()
    if len(body) < 2 or len(body) > max_chars:
        return True
    if not re.search(r"[^\W\d_]", body, re.UNICODE):        # 全是数字/符号
        return True
    if any(word in body for word in NOISE_WORDS):
        return True
    if len(set(body)) <= 2 and len(body) >= 6:              # 分割线之类
        return True
    return False


class VnTextEngine:
    """把钩子 / OCR 两种来源统一成一条文本流。"""

    def __init__(self, *, settings_getter, on_line, on_status=None) -> None:
        self._get_settings = settings_getter
        self._on_line = on_line
        self._on_status = on_status
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._game_id = ""
        self._pid = 0
        self._mode = ""                     # hook | ocr | ""
        self._cli = ""
        self._locked = ""
        self._seen: dict[str, dict] = {}
        self._last_line = ""
        self._lines = 0
        self._error = ""
        self._region = {"x": 0.0, "y": 0.62, "w": 1.0, "h": 0.34}
        self._ocr_last = ""
        self._ocr_streak = 0
        self._lang = "ja-JP"
        self._interval = 0.9

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        with self._lock:
            engine = self._mode
            active = self._active_key()
            threads = sorted(
                ({"key": key, "name": row["name"], "code": row["code"],
                  "count": row["count"], "sample": row["sample"],
                  "active": key == active}
                 for key, row in self._seen.items()),
                key=lambda row: -row["count"])
            return {
                "ok": True,
                "running": bool(engine),
                "engine": engine,
                "game_id": self._game_id,
                "pid": self._pid,
                "cli": self._cli,
                "locked": self._locked,
                "threads": threads[:12],
                "region": dict(self._region),
                "lang": self._lang,
                "lines": self._lines,
                "error": self._error,
            }

    def _push_status(self) -> None:
        if not self._on_status:
            return
        try:
            self._on_status(self.status())
        except Exception as exc:
            config.log(f"vntext status callback failed: {exc}")

    def _active_key(self) -> str:
        if self._locked:
            return self._locked
        if not self._seen:
            return ""
        return max(self._seen.items(), key=lambda item: item[1]["count"])[0]

    # ------------------------------------------------------------------ #
    def start(self, game_id: str, pid: int, mode: str = "auto") -> dict:
        self.stop()
        mode = mode if mode in ("hook", "ocr") else "auto"
        self._stop.clear()
        self._game_id = game_id
        self._pid = int(pid or 0)
        self._error = ""
        self._lines = 0
        self._last_line = ""
        self._seen.clear()
        self._ocr_last = ""
        self._ocr_streak = 0

        settings = self._get_settings() or {}
        self._cli = find_cli(str(settings.get("vntext_tractor_path") or ""))
        self._interval = max(0.3, float(settings.get("vntext_ocr_interval") or 0.9))

        started = False
        if mode in ("auto", "hook") and self._cli and self._pid:
            started = self._start_hook()
            if not started and mode == "hook":
                self._error = "textractor-failed"
        if not started and mode in ("auto", "ocr"):
            started = self._start_ocr()
            if not started:
                from . import ocr as ocr_mod

                state = ocr_mod.status(self._lang)
                self._error = "no-window" if state["lang_ready"] else "no-language"
        if not started and not self._error:
            self._error = "no-textractor" if not self._cli else "hook-failed"
        elif started:
            self._error = ""
        self._push_status()
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                if proc.stdin:
                    try:
                        proc.stdin.write(f"detach -P{self._pid}\n".encode("utf-16-le"))
                        proc.stdin.flush()
                    except Exception:
                        pass
                proc.terminate()
            except Exception as exc:
                config.log(f"textractor cli stop failed: {exc}")
        for thread in list(self._threads):
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.5)
        self._threads.clear()
        if self._mode:
            self._mode = ""
        return self.status()

    # ------------------------------------------------------------------ #
    def _start_hook(self) -> bool:
        # 允许指向 .py / .cmd：自检里用假 CLI 模拟 TextractorCLI 的协议
        cmd = [self._cli]
        low = self._cli.lower()
        if low.endswith(".py"):
            cmd = [sys.executable, self._cli]
        elif low.endswith((".bat", ".cmd")):
            cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", self._cli]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW)
        except Exception as exc:
            config.log(f"textractor launch failed: {exc}")
            return False
        self._proc = proc
        self._mode = "hook"
        try:
            proc.stdin.write(f"attach -P{self._pid}\n".encode("utf-16-le"))
            proc.stdin.flush()
        except Exception as exc:
            config.log(f"textractor attach failed: {exc}")
            self._mode = ""
            return False
        thread = threading.Thread(target=self._hook_loop, args=(proc,), daemon=True,
                                  name="aurora-vntext-hook")
        self._threads.append(thread)
        thread.start()
        config.log(f"vntext hook attached pid={self._pid} cli={self._cli}")
        return True

    def _hook_loop(self, proc: subprocess.Popen) -> None:
        stream = proc.stdout
        if stream is None:
            return
        # 注意：不能用 stream.readline() —— UTF-16LE 的换行是 `0A 00`，
        # 二进制 readline 只吃掉 0x0A，会把后面的 0x00 留在缓冲里让后续每一行都错位。
        buf = bytearray()
        while not self._stop.is_set():
            try:
                chunk = stream.read1(4096)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while True:
                cut = buf.find(b"\n\x00")
                if cut < 0:
                    break
                raw = bytes(buf[:cut + 1])
                del buf[:cut + 2]
                text = raw.decode("utf-16-le", "ignore")
                parsed = parse_hook_line(text)
                if not parsed:
                    continue
                key = parsed["thread"] or parsed["name"] or "默认"
                with self._lock:
                    row = self._seen.setdefault(key, {"name": parsed["name"] or key,
                                                      "code": parsed["code"], "count": 0,
                                                      "sample": ""})
                    row["count"] += 1
                    row["sample"] = parsed["text"][:60]
                    if parsed["code"]:
                        row["code"] = parsed["code"]
                    active = self._active_key()
                # 锁定支持前缀匹配：面板里抄了半截 key 也能锁定
                if self._locked and not (key == self._locked
                                         or key.startswith(self._locked)):
                    continue
                # 自动模式：等某个线程明显领先（≥5 行）之后，才丢弃其它线程的文本。
                # 刚开始时谁都不知道哪个线程是正文，过早过滤会把真正的台词也丢掉。
                leader = self._seen.get(active, {}).get("count", 0)
                if not self._locked and active and key != active and leader >= 5:
                    continue
                self._emit(parsed["text"], "hook")
        if not self._stop.is_set():
            self._error = self._error or "hook-closed"
            self._push_status()

    # ------------------------------------------------------------------ #
    def _start_ocr(self) -> bool:
        from . import ocr

        if not ocr.available() or not ocr.has_language(self._lang):
            return False
        window = screencap.main_window(self._pid)
        if not window:
            return False
        self._mode = "ocr"
        thread = threading.Thread(target=self._ocr_loop, args=(window,), daemon=True,
                                  name="aurora-vntext-ocr")
        self._threads.append(thread)
        thread.start()
        config.log(f"vntext ocr started pid={self._pid} region={self._region}")
        return True

    def _ocr_loop(self, window: dict) -> None:
        from . import ocr

        while not self._stop.is_set():
            shot = screencap.capture(window, self._region)
            if not shot.get("ok"):
                self._error = str(shot.get("error") or "capture-failed")
                self._push_status()
                time.sleep(1.5)
                continue
            result = ocr.recognize_bgr(shot["bgr"], shot["width"], shot["height"], self._lang)
            if not result.get("ok"):
                self._error = str(result.get("error") or "ocr-failed")
                self._push_status()
                time.sleep(1.5)
                continue
            self._error = ""
            text = " ".join(result["text"].split())
            if text and text == self._ocr_last:
                self._ocr_streak += 1
            else:
                self._ocr_streak = 1
                self._ocr_last = text
            # 同一屏文字连续出现两次才认为画完了，避免半截台词
            if text and self._ocr_streak >= 2:
                max_chars = int((self._get_settings() or {}).get("vntext_max_chars") or 1200)
                if not looks_like_noise(text, max_chars):
                    self._emit(text, "ocr", dedupe=False)
            time.sleep(self._interval)

    # ------------------------------------------------------------------ #
    def _emit(self, text: str, source: str, dedupe: bool = True) -> None:
        body = " ".join(str(text or "").split())
        max_chars = int((self._get_settings() or {}).get("vntext_max_chars") or 1200)
        if looks_like_noise(body, max_chars):
            return
        if dedupe and body == self._last_line:
            return
        self._last_line = body
        self._lines += 1
        try:
            self._on_line({"text": body, "source": source, "game_id": self._game_id})
        except Exception as exc:
            config.log(f"vntext line callback failed: {exc}")
        self._push_status()

    # ------------------------------------------------------------------ #
    def lock_thread(self, key: str) -> dict:
        with self._lock:
            self._locked = str(key or "")
        self._push_status()
        return self.status()

    def send_hook(self, code: str) -> dict:
        code = str(code or "").strip()
        proc = self._proc
        if not code or proc is None or not proc.stdin:
            return {"ok": False, "error": "not-hook-mode"}
        try:
            proc.stdin.write(f"{code} -P{self._pid}\n".encode("utf-16-le"))
            proc.stdin.flush()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def set_region(self, region: dict) -> dict:
        with self._lock:
            self._region = {
                "x": max(0.0, min(1.0, float(region.get("x", 0)))),
                "y": max(0.0, min(1.0, float(region.get("y", 0)))),
                "w": max(0.02, min(1.0, float(region.get("w", 1)))),
                "h": max(0.02, min(1.0, float(region.get("h", 0.34)))),
            }
        self._push_status()
        return self.status()
