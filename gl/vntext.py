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


def cli_builds(saved: str = "") -> list[dict]:
    """找到的所有 TextractorCLI 版本（x86 / x64 各算一个），带位数信息。

    Textractor 发布包里根目录是 x86 版，`x64\\` 是 64 位版；galgame 绝大多数是
    32 位，所以注入 32 位游戏必须用 x86 那份，选错会报「只能用 32 位」。
    """
    from . import locale as locale_mod

    seen: list[str] = []
    paths: list[Path] = []
    if saved:
        item = Path(saved)
        paths.append(item / CLI_NAME if item.is_dir() else item)
    for root in candidate_dirs():
        if root.suffix.lower() == ".exe":
            paths += [root]
            continue
        paths += [root / CLI_NAME, root / "x86" / CLI_NAME, root / "x64" / CLI_NAME,
                  root.parent / CLI_NAME]
    out: list[dict] = []
    for path in paths:
        try:
            if not path.is_file():
                continue
            key = str(path).lower()
            if key in seen:
                continue
            seen.append(key)
        except OSError:
            continue
        info = locale_mod.pe_bits(path)
        out.append({"path": str(path), "bits": int(info.get("bits") or 0),
                    "known": bool(info.get("ok"))})
    return out


def find_cli(saved: str = "", bits: int = 0) -> str:
    """按目标游戏位数挑一个 TextractorCLI.exe；找不到返回空串。"""
    builds = cli_builds(saved)
    if not builds:
        return ""
    if saved:
        exact = [b for b in builds if b["path"].lower() == str(saved).lower()]
        if exact:
            return exact[0]["path"]
    if bits:
        match = [b for b in builds if b["bits"] == bits]
        if match:
            return match[0]["path"]
    # 没有位数信息（或没有匹配版本）时优先 x86：galgame 大多数是 32 位
    prefer = [b for b in builds if b["bits"] == 32] or \
             [b for b in builds if "/x86/" in b["path"].replace("\\", "/").lower()] or builds
    return prefer[0]["path"]


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


RUN_RE = re.compile(r"(.)\1{2,}", re.DOTALL)


def collapse_runs(body: str) -> str:
    """把「同一个字连续重复 ≥3 次」压成 1 个（引擎逐字写缓冲时会这样）。

    只压 3 次以上：日文里的「！！」「……」这类两连是有意义的，不能动。
    """
    out = RUN_RE.sub(r"\1", body)
    tokens = out.split()
    if len(tokens) >= 2 and len(set(tokens)) == 1:
        out = tokens[0]                       # 「ABC ABC」这种整串重复
    return out


def collapse_repeats(text: str) -> str:
    """把「整行是同一段重复」还原成一段（Textractor 常见的重复句问题）。

    例：AAABBBCCC → ABC；【佑斗】【佑斗】【佑斗】 → 【佑斗】；
        おおおいいいいーー → おいー
    """
    body = (text or "").strip()
    n = len(body)
    if n >= 4:
        for period in range(1, n // 2 + 1):
            if n % period:
                continue
            block = body[:period]
            if block and block * (n // period) == body:
                return collapse_runs(block)
    return collapse_runs(body)


GARBAGE_RE = re.compile(r"[\ue000-\uf8ff\ufffd\ufff0-\uffff\x00-\x08\x0b\x0c\x0e-\x1f]")
GOOD_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff01-\uff60a-zA-Z0-9\s，。、！？…—「」『』（）()：:；;・～~ー]")

def looks_like_garbage(text: str) -> bool:
    """乱码判定：未转区（非日语代码页）时游戏会吐出假名+私用区/控制符混杂的串。"""
    body = (text or "").strip()
    if not body:
        return True
    if GARBAGE_RE.search(body):
        return True
    # 注意：这一条不能太激进。钩子是分片吐文本的，被截断的短句很容易凑不够
    # 有效字符比例，如果因此判成乱码，真文本所在线程会连着被误杀（反馈里的
    # 「真文本线程被丢弃，之后再也不翻译」就是这么来的）。
    if len(body) >= 6:
        good = len(GOOD_RE.findall(body))
        if good / len(body) < 0.5:
            return True
        if len(set(body)) <= 3:
            return True
    return False

KANA_RE = re.compile(r"[\u3040-\u30ff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def looks_like_dialogue(text: str) -> bool:
    """像不像游戏里的台词：有假名、有一定长度、不是纯符号/菜单。"""
    body = (text or "").strip()
    if len(body) < 4 or len(body) > 400:
        return False
    if looks_like_noise(body):
        return False
    kana = len(KANA_RE.findall(body))
    return kana >= 2 or (kana >= 1 and len(CJK_RE.findall(body)) >= 2)


def looks_like_noise(text: str, max_chars: int = 1200) -> bool:
    """过滤纯数字/符号、过短、系统菜单这类不该翻的行。"""
    body = text.strip()
    if len(body) < 2 or len(body) > max_chars:
        return True
    if not re.search(r"[^\W\d_]", body, re.UNICODE):        # 全是数字/符号
        return True
    if any(word in body for word in NOISE_WORDS):
        return True
    if looks_like_garbage(body):
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
        self._procs: list[subprocess.Popen] = []
        self._targets: list[dict] = []
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
        self._pending: dict[str, dict] = {}
        self._leader = ""
        self._cli_bits = 0
        self._target_bits = 0

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        with self._lock:
            engine = self._mode
            active = self._active_key()
            threads = sorted(
                ({"key": key, "name": row["name"], "code": row["code"],
                  "count": row["count"], "dialogue": row.get("dialogue", 0),
                  "sample": row["sample"],
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
                "cli_bits": self._cli_bits,
                "target_bits": self._target_bits,
                "builds": cli_builds(str((self._get_settings() or {}).get("vntext_tractor_path") or "")),
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

    def _active_kkey_placeholder(self) -> str:
        return ""

    def _active_by_score(self) -> str:
        if not self._seen:
            return ""
        return max(self._seen.items(),
                   key=lambda item: (item[1].get("dialogue", 0), item[1]["count"]))[0]

    def _active_key(self) -> str:
        if self._locked:
            return self._locked
        if self._leader and self._leader in self._seen:
            return self._leader
        return self._active_by_score()

    # ------------------------------------------------------------------ #
    def start(self, game_id: str, pid: int, mode: str = "auto", exe: str = "") -> dict:
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
        saved = str(settings.get("vntext_tractor_path") or "")
        if exe:
            from . import locale as locale_mod

            self._target_bits = int(locale_mod.pe_bits(exe).get("bits") or 0)
        else:
            self._target_bits = 0
        self._cli = find_cli(saved, self._target_bits)
        if self._cli:
            from . import locale as locale_mod

            self._cli_bits = int(locale_mod.pe_bits(self._cli).get("bits") or 0)
        else:
            self._cli_bits = 0
        self._interval = max(0.3, float(settings.get("vntext_ocr_interval") or 0.9))

        self._pending.clear()
        self._leader = ""
        threading.Thread(target=self._flush_loop, daemon=True,
                         name="aurora-vntext-flush").start()
        self._targets = self._collect_targets(self._pid, exe) if self._pid else []
        wanted_bits = {int(row.get("bits") or 0) for row in self._targets} - {0}
        started = False
        # 显式指定的 CLI 与「所有」候选进程位数都不符时才报错
        mismatch = (saved and self._cli_bits and wanted_bits
                    and self._cli_bits not in wanted_bits)
        if mismatch:
            self._error = "wrong-bitness"
        elif mode in ("auto", "hook") and self._cli and self._pid:
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
        procs = list(self._procs) or ([self._proc] if self._proc else [])
        self._proc = None
        self._procs = []
        for proc in procs:
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
    def _collect_targets(self, pid: int, exe: str) -> list[dict]:
        """哪些进程可能在产出文本：主进程 + 它的子孙进程，各读一下 PE 位数。

        关键教训（实测反馈）：64 位游戏常由 32 位子进程渲染文本，文本线程的
        位数与游戏主 exe 不一致；只按主 exe 挑 CLI 就会挂错位数、读出乱码。
        """
        from . import locale as locale_mod, process as process_mod, proctree

        rows: list[dict] = []
        try:
            rows = proctree.snapshot()
        except Exception:
            rows = []
        candidates: list[tuple[int, str]] = []
        try:
            image = process_mod.process_image(pid)
            if image:
                candidates.append((int(pid), image))
        except Exception:
            pass
        if rows:
            try:
                for child in sorted(proctree.descendants(pid, rows) - {int(pid)}):
                    image = process_mod.process_image(child)
                    if image:
                        candidates.append((int(child), image))
            except Exception:
                pass
        out: list[dict] = []
        for child_pid, image in candidates[:6]:
            if os.path.normcase(image).startswith(os.path.normcase(os.environ.get("WINDIR", "C:\\Windows"))):
                continue                      # 系统进程不挂
            bits = int(locale_mod.pe_bits(image).get("bits") or 0)
            out.append({"pid": child_pid, "bits": bits, "path": image})
        if exe and not any(row["bits"] for row in out):
            bits = int(locale_mod.pe_bits(exe).get("bits") or 0)
            out.append({"pid": int(pid), "bits": bits, "path": str(exe)})
        return out

    def _start_hook(self) -> bool:
        targets = getattr(self, "_targets", None) or []
        groups: dict[int, list[int]] = {}
        for row in targets:
            groups.setdefault(int(row.get("bits") or 0), []).append(int(row["pid"]))
        if not groups:
            groups = {self._target_bits or 0: [self._pid]}
        started_any = False
        for bits, pids in groups.items():
            cli = self._cli if (not bits or not self._cli_bits
                                or bits == self._cli_bits) else find_cli(
                str((self._get_settings() or {}).get("vntext_tractor_path") or ""), bits)
            if not cli:
                continue
            if self._start_hook_one(cli, pids):
                started_any = True
        self._mode = "hook" if started_any else ""
        return started_any

    def _start_hook_one(self, cli: str, pids: list[int]) -> bool:
        self._cli = cli
        # 允许指向 .py / .cmd：自检里用假 CLI 模拟 TextractorCLI 的协议
        cmd = [cli]
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
        self._procs.append(proc)
        self._proc = proc
        self._mode = "hook"
        try:
            for target in pids:
                proc.stdin.write(f"attach -P{int(target)}\n".encode("utf-16-le"))
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
                self._buffer_fragment(key, parsed["text"], parsed["name"], parsed["code"])
                continue
                with self._lock:
                    row = self._seen.setdefault(key, {"name": parsed["name"] or key,
                                                      "code": parsed["code"], "count": 0,
                                                      "sample": ""})
                    row["count"] += 1
                    if looks_like_dialogue(parsed["text"]):
                        row["dialogue"] = row.get("dialogue", 0) + 1
                    row["sample"] = parsed["text"][:60]
                    if parsed["code"]:
                        row["code"] = parsed["code"]
                    active = self._active_key()
                # 锁定支持前缀匹配：面板里抄了半截 key 也能锁定
                if self._locked and not (key == self._locked
                                         or key.startswith(self._locked)):
                    continue
                # 自动模式：只在「已经有一个明确在说台词的线程」时，才丢弃别的线程。
                # 之前按总行数判断，会被 Textractor 自己的状态行（例如「连接到 …」）
                # 抢先当上领跑者，把真正的台词线程整个丢掉——反馈里的「翻页不翻译」
                # 就是这个原因。
                if not self._locked and active and key != active:
                    leader_dialogue = self._seen.get(active, {}).get("dialogue", 0)
                    if leader_dialogue >= 3:
                        continue          # 已有明确的台词线程，其它线程一律不看
                self._emit(parsed["text"], "hook")
        if not self._stop.is_set():
            self._error = self._error or "hook-closed"
            self._push_status()

    # ------------------------------------------------------------------ #
    # 钩子文本是分片到达的：先按线程缓冲、合并成完整一句，静默 0.35s 再翻译。
    # 不这样做的话，截断的半句会被翻译错，还容易被误判成乱码。
    FRAGMENT_IDLE = 0.35

    def _buffer_fragment(self, key: str, text: str, name: str, code: str) -> None:
        now = time.time()
        with self._lock:
            row = self._seen.setdefault(key, {"name": name or key, "code": code,
                                              "count": 0, "sample": "", "dialogue": 0,
                                              "last_seen": now})
            row["last_seen"] = now
            if code:
                row["code"] = code
            pending = self._pending.get(key)
            if pending:
                old = pending["text"]
                if text.startswith(old) and len(text) > len(old):
                    pending["text"] = text      # 同一句被补全
                    pending["at"] = now
                    return
                if old.startswith(text):
                    pending["at"] = now         # 重复/回退，忽略
                    return
                # 引擎可能把「缺字的前半段」先写出来、再补一份更完整的：
                # 只要一份基本包含另一份，就保留更长的那份，别当成新句子
                shorter, longer = (old, text) if len(old) <= len(text) else (text, old)
                if shorter and longer.find(shorter[:max(4, len(shorter) // 2)]) >= 0 \
                        and len(shorter) >= 0.6 * len(longer):
                    pending["text"] = longer
                    pending["at"] = now
                    return
        if pending:
            self._flush_thread(key)             # 上一句先落地
        with self._lock:
            self._pending[key] = {"text": text, "at": time.time()}

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.12)
            now = time.time()
            with self._lock:
                keys = [k for k, row in self._pending.items()
                        if now - row["at"] >= self.FRAGMENT_IDLE]
            for key in keys:
                self._flush_thread(key)

    def _flush_thread(self, key: str) -> None:
        with self._lock:
            row = self._pending.pop(key, None)
        if not row:
            return
        text = " ".join(str(row["text"]).split())
        if not text:
            return
        self._register_line(key, text)

    def _register_line(self, key: str, text: str) -> None:
        """记账（台词计数/领跑线程）并按需发射。"""
        with self._lock:
            row = self._seen.setdefault(key, {"name": key, "code": "", "count": 0,
                                              "sample": "", "dialogue": 0,
                                              "last_seen": time.time()})
            row["count"] += 1
            if looks_like_dialogue(text):
                row["dialogue"] = row.get("dialogue", 0) + 1
            row["sample"] = text[:60]
            leader = self._leader
            leader_seen = self._seen.get(leader, {}).get("last_seen", 0) if leader else 0
            if not leader or (leader != key and time.time() - leader_seen > 20):
                if row.get("dialogue", 0) >= 3:
                    self._leader = self._active_by_score()
            active = self._active_key()
            leader_dialogue = self._seen.get(active, {}).get("dialogue", 0)
        if self._locked and not (key == self._locked or key.startswith(self._locked)):
            return
        # 已经有明确在说台词的线程时，其它线程不看（乱码多是别线程产物）
        if not self._locked and active and key != active and leader_dialogue >= 3:
            return
        self._emit(text, "hook")

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
        body = " ".join(collapse_repeats(str(text or "")).split())
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
