"""游戏内翻译自检：钩子协议 / 噪声过滤 / 流式翻译 / 术语表 / 缓存 / OCR 状态。

不需要真的装 Textractor：这里生成一个「假 TextractorCLI」脚本，按它真实的
stdin/stdout 协议（UTF-16LE、`[handle:pid:addr:ctx:ctx2:线程名:hook码] 正文`）
吐模拟台词；翻译侧则起一个本地假 LLM（SSE 流式）。
结果写入 tools/vntext-report.txt。
"""
from __future__ import annotations

import http.server
import io
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox" / "vntext"
DATA = SANDBOX / "data"
REPORT = Path(__file__).resolve().parent / "vntext-report.txt"
FAKE_CLI = SANDBOX / "fake_textractor.py"

os.environ["AURORA_DATA"] = str(DATA)

from gl import linetrans, ocr, overlay, screencap, vntext  # noqa: E402

failed = 0

FAKE_CLI_SRC = '''"""假 TextractorCLI：只实现我们用到的那部分协议。"""
import sys, time

def emit(handle, name, code, text):
    line = f"[{handle}:000004D2:00000000:0:0:{name}:{code}] {text}\\n"
    sys.stdout.buffer.write(line.encode("utf-16-le"))
    sys.stdout.buffer.flush()

attached = False
while True:
    raw = sys.stdin.buffer.readline()
    if not raw:
        break
    cmd = raw.decode("utf-16-le", "ignore").strip()
    if cmd.startswith("attach"):
        attached = True
        # 菜单线程先说一句（噪声，应该被过滤掉）
        emit("00000001", "menu", "HS1@0", "セーブ")
        emit("00000001", "menu", "HS1@0", "ロード")
        for i, text in enumerate([
            "彼女は静かに微笑んだ。",
            "「また明日ね」と小さく呟いて、",
            "教室をあとにする。",
        ]):
            emit("00000002", "dialogue", "HS2@0", text)
            time.sleep(0.05)
        emit("00000001", "menu", "HS1@0", "設定")
    elif cmd.startswith("detach"):
        break
    else:
        # 手写的 hook 码：用同一个线程回显一条，确认命令透传成功
        emit("00000002", "dialogue", cmd.split()[0] if cmd.split() else "manual",
             "手動フックのテスト")
'''


class MockLLM(http.server.BaseHTTPRequestHandler):
    seen_bodies: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        MockLLM.seen_bodies.append(body)
        user = ""
        for message in body.get("messages") or []:
            if message.get("role") == "user":
                user = message.get("content") or ""
        answer = "她静静地微笑了。" if "微笑" in user else "（译文）"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()
        for piece in (answer[:2], answer[2:4], answer[4:]):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.05)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):  # 静音
        return


def main() -> int:
    global failed
    out = io.StringIO()

    def write(line: str = "") -> None:
        out.write(line + "\n")
        print(line, flush=True)

    def check(label: str, ok: bool, detail="") -> bool:
        global failed
        if not ok:
            failed += 1
        write(f"  {'OK ' if ok else 'BAD'} {label}" + (f"  {detail}" if detail else ""))
        return ok

    shutil.rmtree(SANDBOX, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)
    FAKE_CLI.write_text(FAKE_CLI_SRC, encoding="utf-8")

    write("Aurora 游戏内翻译自检")
    write("=" * 52)

    # ------------------------------------------------------------ 协议解析
    write("\n[钩子行解析]")
    row = vntext.parse_hook_line(
        "[00000002:000004D2:00000000:0:0:dialogue:HS2@0] 彼女は静かに微笑んだ。")
    check("解析线程名/hook码/正文", bool(row) and row["name"] == "dialogue"
          and row["code"] == "HS2@0" and row["text"].startswith("彼女"), str(row))
    check("非协议行按纯文本处理", (vntext.parse_hook_line("just text") or {}).get("text") == "just text")
    check("空行忽略", vntext.parse_hook_line("") is None)

    write("\n[噪声过滤]")
    cases = [("セーブ", True), ("12345", True), ("……", True), ("あ", True),
             ("彼女は静かに微笑んだ。", False), ("「また明日ね」と小さく呟いて、", False)]
    for text, want_noise in cases:
        got = vntext.looks_like_noise(text)
        check(f"{'过滤' if want_noise else '保留'}：{text[:16]}", got == want_noise, str(got))

    # ------------------------------------------------------------ 钩子文本源
    write("\n[钩子文本源（假 TextractorCLI）]")
    settings = {"vntext_tractor_path": str(FAKE_CLI), "vntext_max_chars": 1200}
    lines: list[dict] = []
    statuses: list[dict] = []
    engine = vntext.VnTextEngine(settings_getter=lambda: settings,
                                 on_line=lines.append, on_status=statuses.append)
    state = engine.start("probe-game", 1234, "hook")
    check("attach 成功并进入 hook 模式", state.get("running") and state["engine"] == "hook",
          str(state.get("error")))
    deadline = time.time() + 8
    while time.time() < deadline and len(lines) < 3:
        time.sleep(0.2)
    texts = [row["text"] for row in lines]
    check("收到台词且顺序正确",
          len(lines) >= 3 and texts[0].startswith("彼女"), str(texts[:4]))
    check("菜单类噪声被挡掉", not any("セーブ" in t or "ロード" in t or "設定" in t for t in texts),
          str(texts))
    status = engine.status()
    names = {t["name"] for t in status["threads"]}
    check("线程列表有记录", "dialogue" in names and "menu" in names, str(names))

    full_key = next((t["key"] for t in engine.status()["threads"]
                     if t["name"] == "dialogue"), "")
    lock = engine.lock_thread(full_key)
    check("能锁定线程（用线程列表里的完整 key）",
          bool(full_key) and lock.get("locked") == full_key, f"{full_key} -> {lock.get('locked')}")
    engine.lock_thread(full_key[:8])          # 前缀也应该能锁定
    check("锁定支持前缀", engine.status()["locked"] == full_key[:8],
          engine.status()["locked"])
    engine.send_hook("HS9@1234")
    time.sleep(1.2)
    check("手写 hook 码能透传并回文本",
          any("手動フック" in row["text"] for row in lines), str(texts[-3:]))
    engine.lock_thread("")
    engine.stop()
    check("停止后不再运行", not engine.status()["running"])

    # ------------------------------------------------------------ 流式翻译
    write("\n[流式翻译 / 上下文 / 术语表 / 缓存]")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    settings2 = {
        "translate_base_url": f"http://127.0.0.1:{port}",
        "translate_api_key": "test-key",
        "translate_model": "mock",
        "translate_target": "zh-CN",
        "vntext_context_lines": 2,
        "proxy_mode": "direct",
    }
    events: list[tuple[str, dict]] = []
    translator = linetrans.LineTranslator(settings_getter=lambda: settings2,
                                          on_event=lambda kind, payload: events.append((kind, payload)))
    linetrans.save_glossary({"global": {"彼女": "她"}, "games": {}, "version": 2})
    translator.submit("彼女は静かに微笑んだ。", game_id="probe-game")
    deadline = time.time() + 20
    while time.time() < deadline:
        if any(kind == "done" for kind, _ in events):
            break
        time.sleep(0.2)
    kinds = [kind for kind, _ in events]
    check("有 start / delta / done 事件",
          "start" in kinds and "delta" in kinds and kinds[-1] == "done"
          and kinds.index("start") < kinds.index("delta"), str(kinds[:8]))
    deltas = "".join(payload.get("delta") or "" for kind, payload in events if kind == "delta")
    done = next((payload for kind, payload in events if kind == "done"), {})
    check("流式拼出完整译文", deltas == done.get("translation") == "她静静地微笑了。",
          f"{deltas!r} / {done.get('translation')!r}")
    body = MockLLM.seen_bodies[-1] if MockLLM.seen_bodies else {}
    prompt = " ".join(message.get("content", "") for message in body.get("messages") or [])
    check("术语表进了提示词", "彼女 → 她" in prompt, prompt[:80])
    check("带上了上文", "上文" in prompt, prompt[:120])
    check("请求是流式", body.get("stream") is True)

    events.clear()
    translator.submit("彼女は静かに微笑んだ。", game_id="probe-game")
    deadline = time.time() + 8
    while time.time() < deadline:
        if any(kind == "done" for kind, _ in events):
            break
        time.sleep(0.1)
    done = next((payload for kind, payload in events if kind == "done"), {})
    check("重复台词命中缓存", done.get("provider") == "cache", str(done.get("provider")))

    events.clear()
    translator.submit("「また明日ね」と小さく呟いて、", game_id="probe-game")
    time.sleep(0.4)
    history = translator.history(5)
    check("历史记录累积", len(history) >= 2, f"{len(history)} 条")
    check("暂停后不再提交", translator.set_paused(True).get("paused") is True
          and translator.submit("テスト", game_id="probe-game") is None)
    translator.set_paused(False)
    server.shutdown()

    # ------------------------------------------------------------ OCR 状态
    # ------------------------------------------------------------ 位数选择
    # ------------------------------------------------------------ Phase 0/1 用例
    write("\n[同一句多形态去重（DRACU RIOT 实测样本）]")
    lines3: list[dict] = []
    eng3 = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                               on_line=lines3.append)
    for text in ("【佑斗】【佑斗】【佑斗】「お前、出発してからそればっかりだな」",
                 "「おお前前、出出発発ししててかかららそそれればばっっかりりだだな」",
                 "「お前、出発してからそればっかりだな」",
                 "「また明日ね」と小さく呟いて、"):
        eng3._register_line("thread-A", text)
    check("三形态只翻一次，下一句正常", len(lines3) == 2,
          f"发出 {len(lines3)} 条：{[row['text'][:16] for row in lines3]}")
    check("合并计数有记录", eng3.status().get("merged", 0) >= 2,
          str(eng3.status().get("merged")))

    write("\n[重复折叠（保留有意义的双连）]")
    for src, want in (("AAABBBCCC", "ABC"), ("【佑斗】【佑斗】【佑斗】", "【佑斗】"),
                      ("ABC ABC", "ABC"), ("やった！！", "やった！！"),
                      ("そう……。", "そう……。")):
        got = vntext.collapse_repeats(src)
        check(f"{src[:14]} -> {want[:10]}", got == want, got)

    write("\n[引擎标识与规则集]")
    check("TVP/KIRIKIRI 规则可取出",
          vntext.profile_for("TVP/KIRIKIRI").get("collapse_doubling") is True
          and "GetTextExtentPoint32W" in vntext.profile_for("TVP/KIRIKIRI")["hook_hint"])
    check("WillPlus 规则里给出 OCR 建议",
          "OCR" in vntext.profile_for("WillPlus")["hook_hint"])
    check("未知引擎回落到 default", vntext.profile_for("不存在").get("name_prefix") is True)
    check("detect_engine 对无效 pid 不炸", vntext.detect_engine(0) == "unknown")

    write("\n[64 位主进程 + 32 位子进程：两套 CLI 同时挂]")
    frag = SANDBOX / "multi_cli.py"
    frag.write_text(FAKE_CLI_SRC, encoding="utf-8")
    eng4 = vntext.VnTextEngine(settings_getter=lambda: {"vntext_tractor_path": str(frag),
                                                        "vntext_max_chars": 1200},
                               on_line=lambda row: None)
    eng4._cli = str(frag)
    eng4._cli_bits = 0
    eng4._targets = [{"pid": 111, "bits": 64, "path": "C:\\g\\main.exe"},
                     {"pid": 222, "bits": 32, "path": "C:\\g\\reader.exe"}]
    ok4 = eng4._start_hook()
    time.sleep(1.2)
    procs4 = len(eng4._procs)
    eng4.stop()
    check("两种位数各起一个实例", ok4 and procs4 == 2, f"实例数={procs4}")

    write("\n[TextractorCLI 位数选择]")
    win = Path(os.environ.get("WINDIR", r"C:\Windows"))
    build_root = SANDBOX / "TL"
    (build_root / "x86").mkdir(parents=True, exist_ok=True)
    (build_root / "x64").mkdir(parents=True, exist_ok=True)
    shutil.copy2(win / "System32" / "ping.exe", build_root / "x64" / "TextractorCLI.exe")
    shutil.copy2(win / "SysWOW64" / "ping.exe", build_root / "x86" / "TextractorCLI.exe")
    builds = vntext.cli_builds(str(build_root))
    check("能同时发现 x86 与 x64 两个版本",
          {row["bits"] for row in builds} == {32, 64}, str([(r["bits"], r["path"][-28:]) for r in builds]))
    check("32 位游戏挑 x86 版",
          vntext.find_cli(str(build_root), 32).lower().endswith("x86\\textractorcli.exe"),
          vntext.find_cli(str(build_root), 32))
    check("64 位游戏挑 x64 版",
          vntext.find_cli(str(build_root), 64).lower().endswith("x64\\textractorcli.exe"),
          vntext.find_cli(str(build_root), 64))
    check("不知道位数时默认 x86（galgame 多数是 32 位）",
          vntext.find_cli(str(build_root)).lower().endswith("x86\\textractorcli.exe"))
    bad_settings = {"vntext_tractor_path": str(build_root / "x64" / "TextractorCLI.exe"),
                    "vntext_max_chars": 1200}
    engine2 = vntext.VnTextEngine(settings_getter=lambda: bad_settings, on_line=lambda row: None)
    state2 = engine2.start("bits", 1234, "hook", exe=str(win / "SysWOW64" / "ping.exe"))
    engine2.stop()
    check("显式指定错位数时明确报 wrong-bitness",
          state2.get("error") == "wrong-bitness" and state2.get("cli_bits") == 64
          and state2.get("target_bits") == 32,
          f"{state2.get('error')} cli={state2.get('cli_bits')} target={state2.get('target_bits')}")

    write("\n[OCR]")
    state = ocr.status("ja-JP")
    write(f"  winrt 可用={state['available']} 语言={state['languages']} 日语就绪={state['lang_ready']}")
    if state["lang_ready"]:
        check("日语 OCR 可用（本机已装组件）", True, "")
    else:
        check("缺日语 OCR 组件时给出明确错误",
              (ocr.recognize_bgr(b"\x00" * 300, 10, 10, "ja-JP").get("error") == "no-language"))
        write("  （要在本机用 OCR 模式：设置 → 时间和语言 → 语言和区域 → 添加日语 → 勾选「光学字符识别」）")

    write("\n[窗口捕获]")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = int(user32.GetForegroundWindow())
    if hwnd:
        shot = screencap.capture({"hwnd": hwnd})
        check("能抓到前台窗口画面", shot.get("ok") and len(shot.get("bgr") or b"") > 1000,
              f"{shot.get('width')}x{shot.get('height')} {shot.get('source')}")
        sub = screencap.capture({"hwnd": hwnd}, {"x": 0.0, "y": 0.5, "w": 1.0, "h": 0.5})
        check("相对区域裁剪生效",
              sub.get("ok") and sub.get("height", 0) < shot.get("height", 1),
              f"{sub.get('width')}x{sub.get('height')}")
    else:
        check("前台窗口存在", False, "没有前台窗口，跳过")

    write("\n[文件对话框过滤器]")
    # 曾经踩过：file_types 少了 *.exe 通配符，pywebview 直接抛异常，
    # 前端 await 之后静默失败，表现为「点『选择…』没反应」。
    import re
    from webview.util import parse_file_type

    for spec in ("可执行文件 (*.exe)", "命令行程序 (*.exe)", "所有文件 (*.*)",
                 "图片 (*.jpg;*.jpeg;*.png)"):
        try:
            parse_file_type(spec)
            ok = True
        except Exception:
            ok = False
        check(f"合法过滤器：{spec}", ok)
    source = (ROOT / "gl" / "api.py").read_text(encoding="utf-8")
    bad = [m.group(1).strip()[:40] for m in re.finditer(r"file_types=\(([^)]*)\)", source)
           if "*" not in m.group(1)]
    check("api.py 里所有 file_types 都带通配符", not bad, str(bad))

    write("\n[悬浮窗设置]")
    cfg = {"vntext_overlay": {"x": 0, "y": 0, "w": 760, "h": 150, "font": 20,
                              "opacity": 0.9, "mode": "translated", "click_through": True}}
    box = overlay.Overlay(get_settings=lambda: cfg,
                          set_option=lambda key, value: cfg.__setitem__(key, value),
                          on_action=lambda name, payload: {"ok": True})
    payload = box.initial_payload()
    check("悬浮窗默认样式正确",
          payload["style"]["mode"] == "translated" and payload["click_through"] is True,
          str(payload["style"]))
    check("保存位置写回设置", box.save_bounds(100, 200, 800, 180).get("ok")
          and cfg["vntext_overlay"]["x"] == 100, str(cfg["vntext_overlay"]))
    check("字号/透明度有上下限",
          box.set_style({"font": 99}).get("style", {}).get("font") == 40
          and box.set_style({"opacity": 0.1}).get("style", {}).get("opacity") == 0.35)

    write("\n结论: " + ("全部通过" if not failed else f"{failed} 项失败"))
    REPORT.write_text(out.getvalue(), encoding="utf-8")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
