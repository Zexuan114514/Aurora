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
        # 引擎把一句话折成多行时，CLI 会原样逐行打印，只有第一行带 [handle:...] 头
        sys.stdout.buffer.write(
            "[00000003:000004D2:00000000:0:0:wrapped:HS3@0] 「ごめん、そのつもりだったんだけど完全に思い付き。\\n"
            "夜の洋館の雰囲気がとても良くて、そこでの仕事を見させて\\n"
            "もらったら参考になるかなと」\\n".encode("utf-16-le"))
        sys.stdout.buffer.flush()
        time.sleep(0.05)
        # 说话人名字单独一条（Escu:de 实测）：不该单独翻，要并成下一句的【名字】
        emit("00000005", "speaker", "HS5@0", "アマリリス")
        time.sleep(1.2)          # 真实场景里名字是每次翻页重发一次，间隔远大于 0.35s
        emit("00000003", "wrapped", "HS3@0", "「参考、ですか。確か作家の先生をされていると伺いました」")
        time.sleep(1.2)
        emit("00000005", "speaker", "HS5@0", "アマリリス")
        time.sleep(1.2)
        emit("00000003", "wrapped", "HS3@0", "「まだまだ勉強中です」")
        time.sleep(1.2)
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


def settle(engine) -> None:
    """直接喂 `_register_line` 的用例要手动跨过「定稿窗口」。

    正常运行时行会先在候选池里压 0.55s（等同一句的缺字版/完整版都到齐），
    自检里没有这个等待，用 flush_staged() 一次性定稿。
    """
    engine.flush_staged()


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
    # 假 CLI 会连发：3 句台词 → 折行 3 行的长句 → 名字 → 两句对话（其中一句带【名字】）
    # 一次等够再断言，别用「等 3 条就动手」这种会和缓冲打架的写法
    deadline = time.time() + 15
    while time.time() < deadline and len(lines) < 7:
        time.sleep(0.2)
    texts = [row["text"] for row in lines]
    check("收到台词且顺序正确",
          len(lines) >= 3 and texts[0].startswith("彼女"), str(texts[:4]))
    check("菜单类噪声被挡掉", not any("セーブ" in t or "ロード" in t or "設定" in t for t in texts),
          str(texts))
    # Escu:de 实测：一句话被折成 3 行，续行没有 [handle:...] 头，必须并回一句
    wrapped = [t for t in texts if t.startswith("「ごめん")]
    check("多行文本被并回一句（折行续行）",
          len(wrapped) == 1 and "夜の洋館" in wrapped[0] and "もらったら参考になるかなと」" in wrapped[0],
          str(wrapped))
    named = [t for t in texts if t.startswith("【アマリリス】")]
    check("说话人名字并进下一句当【名字】",
          len(named) >= 1 and all("「" in t for t in named),
          str(named[:2]))
    check("名字行不再单独翻一遍", texts.count("アマリリス") <= 1, str(texts))
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
    deadline = time.time() + 5
    while time.time() < deadline and not any("手動フック" in row["text"] for row in lines):
        time.sleep(0.2)
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
    # 快速连翻时旧请求不能被掐断：排队后每句都要有 done（RIDDLE JOKER 实测场景）
    burst = ["「一句目のセリフです」", "「二句目のセリフです」", "「三句目のセリフです」"]
    for row in burst:
        translator.submit(row, game_id="probe-game")
    deadline = time.time() + 30
    while time.time() < deadline:
        done_texts = {payload.get("text") for kind, payload in events if kind == "done"}
        if all(row in done_texts for row in burst):
            break
        time.sleep(0.2)
    done_texts = {payload.get("text") for kind, payload in events if kind == "done"}
    check("连翻三句每句都有译文（不再掐断旧请求）",
          all(row in done_texts for row in burst),
          f"done={sorted(t[:8] for t in done_texts)}")

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
    settle(eng3)
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

    # 这几条是 DRACU RIOT 真机钩子行的原文（tools/vntext_live.py 抓的），
    # 一行 = 逐字×3 形态 + ×2 形态 + 干净形态。清洗后必须只剩那句台词。
    write("\n[真机三形态文本清洗（DRACU RIOT 实测行）]")
    for name, src, want in (
        ("逐字×3+×2+干净（无引号）",
         "今今今ににに至至至るるるととといいいうううわわわけけけだだだ。。。"
         "今今にに至至るるとといいううわわけけだだ。。今に至るというわけだ。",
         "今に至るというわけだ。"),
        ("名字×3 + 「」分隔三形态",
         "【 佑斗 】【 佑斗 】【 佑斗 】「「「でででもももおおお前前前、、、どどどうううしししててて"
         "俺俺俺ををを誘誘誘っっってててくくくれれれたたたんんんだだだ？？？」」」"
         "「「ででももおお前前、、どどううししてて俺俺をを誘誘っっててくくれれたたんんだだ？？」」"
         "「でもお前、どうして俺を誘ってくれたんだ？」",
         "【佑斗】でもお前、どうして俺を誘ってくれたんだ？"),
        ("三形态里有空格（标点差异）",
         "【旅の相方】【旅の相方】【旅の相方】「「「えええ？？？ あああーーー、、、そそそれれれははは、、、"
         "そそそのののーーー」」」「「ええ？？ ああーー、、そそれれはは、、そそののーー」」"
         "「え？ あー、それは、そのー」",
         "【旅の相方】え？ あー、それは、そのー"),
        ("最后一份是最干净的（弃掉残片）",
         "【旅の相方】【旅の相方】【旅の相方】「「「あああっっっ、、、ああああああ！！！ "
         "そそそろろろそそそろろろ着着着くくくみみみたたたいいいだだだ！！！ 用用用いいいだだだ！！！ "
         "用用用意意意しししななな意意意しししなななくくくちちちゃゃゃ！！！くくくちちちゃゃゃ！！！」」」」」」"
         "「「「「ああああっっっっ、、、、ああああああああ！！！！ "
         "そそそそろろろろそそそそろろろろ着着着着くくくくみみみみたたたたいいいいだだだだ！！！！ "
         "用用用用意意意意ししししななななくくくくちちちちゃゃゃゃ！！！！」」」」"
         "「「ああっっ、、ああああ！！ そそろろそそろろ着着くくみみたたいいだだ！！ "
         "用用意意ししななくくちちゃゃ！！」」",
         "【旅の相方】あっ、あ！！ そろそろ着くみたいだ！ 用意しなくちゃ！"),
    ):
        got = vntext.clean_hook_text(src)
        check(name, got == want, got)
    # 反向用例：正常的引号/重复不能被误伤
    for name, src in (("相邻两句对话不动", "「そうか」「ああ」"),
                      ("同一行的两句对话不动", "「おはよう」と彼女は言った。「今日もいい天気だね」"),
                      ("正常叠字不动", "ここにいるよ。ええ、そうよ")):
        got = vntext.clean_hook_text(src)
        check(name, got == src, got)
    check("纯名字行不产出台词", vntext.clean_hook_text("【佑斗】【佑斗】【佑斗】") == "", "")

    # RIDDLE JOKER 实测：同一个进程里两条同名 KiriKiriZ 钩子线程交替抢先吐同一句。
    # 旧逻辑「先去重再门禁」会把非领跑线程那句登记进去再由门禁丢掉，等领跑线程
    # 送来同一句时又被当成重复 → 整句消失（表现为一句有一句没有）。
    write("\n[两个同名线程交替抢先（RIDDLE JOKER 实测场景）]")
    raced: list[dict] = []
    eng_race = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                   on_line=raced.append)
    for index in range(3):                      # 先把 thread-A 养成领跑线程
        eng_race._register_line("thread-A", [
            "「おはよう、今日もいい天気だね」",
            "「昨日の資料はもう目を通したかい？」",
            "「それなら安心だ、ありがとう」",
        ][index])
    settle(eng_race)
    check("领跑线程已确定", eng_race.status().get("locked", "") == ""
          and len(raced) == 3, f"发出 {len(raced)} 条")
    raced.clear()
    eng_race._register_line("thread-B", "「交互に先を越すテスト台詞」")   # B 抢先
    eng_race._register_line("thread-A", "「交互に先を越すテスト台詞」")   # A 随后送同一句
    settle(eng_race)
    check("抢先的副本不会把整句吞掉（只翻一次）", len(raced) == 1,
          f"发出 {len(raced)} 条：{[row['text'][:18] for row in raced]}")
    check("同一句的两份被合并计数", eng_race.status().get("merged", 0) >= 1,
          str(eng_race.status().get("merged")))
    # 不像台词的杂讯仍要被门禁挡掉（菜单动画之类）
    raced.clear()
    eng_race._register_line("thread-C", "迷宮探索中継続表示切替案内")   # 无假名、非短名，非台词
    settle(eng_race)
    check("领跑线程之外的非台词仍被挡掉", len(raced) == 0, f"发出 {len(raced)} 条")
    check("门禁计数有记录", eng_race.status().get("gated", 0) >= 1,
          str(eng_race.status().get("gated")))

    write("\n[噪声：窗口标题 / 菜单栏]")
    check("菜单栏（(&F)(&S)）当噪声",
          vntext.looks_like_noise("ファイル(&F)画面(&S)テキスト言語(&L)進行制御(&M)ヘルプ(&H)(ver1.13)+"))
    check("正常台词不误判", not vntext.looks_like_noise("「俺の服も半袖にしてくれない？」"))
    check("窗口标题与 exe 名可比对",
          vntext.norm_name("RIDDLE JOKER") == vntext.norm_name("RiddleJoker.exe")[:11],
          f"{vntext.norm_name('RIDDLE JOKER')} vs {vntext.norm_name('RiddleJoker.exe')}")

    # 白色相簿2 实测：同一进程里既有乱码线程、菜单线程，又有视频窗口标题与文件名，
    # 自动选线程不能被它们带跑
    write("\n[白色相簿2 实测：乱码/视频/菜单线程不参与]")
    check("混入天城文/希伯来文的乱码判为噪声",
          vntext.looks_like_noise("इव孙ؔ䝬\u05cb孙ؔ灐灒灟灹灱炄灰"))
    check("视频窗口标题判为噪声", vntext.looks_like_noise("ActiveMovie Window"))
    check("视频文件名判为噪声", vntext.looks_like_noise("mv01"))
    check("短台词仍算台词", vntext.looks_like_dialogue("「あ…」"))
    wa2: list[dict] = []
    eng_wa2 = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                  on_line=wa2.append)
    for key, text in (
        ("3:3EBC:7", "इவ孙ؔ䝬\u05cb孙ؔ灐灒灟灹灱炄灰"),
        ("4:3EBC:7", "画面設定環境設定システムヘルプ"),
        ("5:3EBC:7", "ActiveMovie WindowActiveMovie Window"),
        ("6:3EBC:4", "mv01"),
        ("7:3EBC:4", "「あ…」"),
        ("7:3EBC:4", "とうとう、降ってきた。"),
        ("7:3EBC:4", "街はすっかり白に染まっている。"),
        ("3:3EBC:7", "灱炄灰灱炄灰इவ孙ؔ䝬\u05cb孙ؔ灐灒灟灹灱炄灰"),
    ):
        eng_wa2._register_line(key, text)
    settle(eng_wa2)
    check("只发射真台词那三句",
          [row["text"] for row in wa2] == ["「あ…」", "とうとう、降ってきた。",
                                           "街はすっかり白に染まっている。"],
          str([row["text"][:20] for row in wa2]))
    check("活动线程指向真文本线程", eng_wa2._active_key().startswith("7:3EBC"),
          eng_wa2._active_key())

    # SUMMER POCKETS REFLECTION BLUE（SiglusEngine）实测：系统线程疯狂刷场景名/资源表，
    # 另有只吐汉字的「缺字变体」；真台词线程有 4 条（SiglusEngine2/3/4）
    write("\n[SiglusEngine 实测：系统刷屏 + 缺字变体]")
    check("场景名刷屏判为系统刷屏",
          vntext.looks_like_system_spam("10_プロローグ0725" * 6))
    check("资源表判为系统刷屏",
          vntext.looks_like_system_spam("bg_siro|" + "none" * 8))
    check("内部标记判为系统刷屏", vntext.looks_like_system_spam("__sys_scdata_init__" * 3))
    check("正常台词不是系统刷屏",
          not vntext.looks_like_system_spam("潮風が顔に吹き付ける。俺は目を細めた。"))
    sprb: list[dict] = []
    eng_sprb = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                   on_line=sprb.append)
    for key, text in (("sys", "10_プロローグ0725" * 6),
                      ("sys", "__sys_scdata_init__" * 3),
                      ("real", "鳥の群れが飛んでいる。"),
                      ("gdi", "群群飛飛"),
                      ("real", "船を追い越して。島に向かって。"),
                      ("gdi", "越島"),
                      ("real", "珍しい光景だな、と思った。")):
        eng_sprb._register_line(key, text)
    settle(eng_sprb)
    check("只发射真台词（刷屏与缺字变体都挡掉）",
          [row["text"] for row in sprb] == ["鳥の群れが飛んでいる。",
                                            "船を追い越して。島に向かって。",
                                            "珍しい光景だな、と思った。"],
          str([row["text"][:16] for row in sprb]))
    check("活动线程落在真文本线程", eng_sprb._active_key().startswith("real"),
          eng_sprb._active_key())
    check("整串成对的名字才折一半",
          vntext.fold_full_doubling("女女子子") == "女子"
          and vntext.fold_full_doubling("アマリリス") == "アマリリス")

    # 秽翼のユースティア（BGI/Ethornell）实测：同一个进程里两条钩子线程一起吐同一句 ——
    # `TextOutA`（按字形抓，字体查不到的字就丢）给缺字版 `視界黒塞`，引擎自己的
    # `BGI` 钩子紧接着给完整版 `視界を黒い何かが塞いだ。`。旧版会把两份都翻一遍，
    # 表现为「同一句先出错误译文、再出正确译文」。
    write("\n[BGI/Ethornell 实测：缺字版与完整版只翻一次]")
    check("缺字版判定为同一句的缺字版",
          vntext.missing_chars_variant("視界黒塞", "視界を黒い何かが塞いだ。")
          and vntext.missing_chars_variant("方め辛活耐だろ？",
                                           "こんな死に方をするために、"
                                           "わたしは辛い生活に耐えてきたのだろうか？"))
    check("正常的相邻两句不会被判成缺字版",
          not vntext.missing_chars_variant("「そうか」", "「そうか、それはよかった」")
          and not vntext.missing_chars_variant("「おはよう」", "「今日もいい天気だね」"))
    bgi_samples = [
        ("4:202C:7:TextOutA", "視界黒塞"),
        ("3:202C:4:BGI", "視界を黒い何かが塞いだ。"),
        ("4:202C:7:TextOutA", "遅大足気づ"),
        ("3:202C:4:BGI", "少し遅れて、それが大きな足だと気づいた。"),
        ("4:202C:7:TextOutA", "おぐ路地染み"),
        ("3:202C:4:BGI", "おそらく、もうすぐわたしも路地の染みになる。"),
        ("4:202C:7:TextOutA", "方め辛活耐だろ？"),
        ("3:202C:4:BGI", "こんな死に方をするために、わたしは辛い生活に耐えてきたのだろうか？"),
    ]
    bgi_lines: list[dict] = []
    eng_bgi = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                  on_line=bgi_lines.append)
    for key, text in bgi_samples:
        eng_bgi._register_line(key, text)
    settle(eng_bgi)
    check("只发射完整版（缺字版被并掉）",
          [row["text"] for row in bgi_lines]
          == ["視界を黒い何かが塞いだ。", "少し遅れて、それが大きな足だと気づいた。",
              "おそらく、もうすぐわたしも路地の染みになる。",
              "こんな死に方をするために、わたしは辛い生活に耐えてきたのだろうか？"],
          str([row["text"][:18] for row in bgi_lines]))
    check("缺字版没有被当成说话人名字",
          not any(row["text"].startswith("【") for row in bgi_lines),
          str([row["text"][:18] for row in bgi_lines]))
    check("并掉的缺字版有计数", eng_bgi.status().get("merged", 0) >= 4,
          str(eng_bgi.status().get("merged")))
    # 反过来（完整版先到、缺字版后到）也要并掉
    bgi2: list[dict] = []
    eng_bgi2 = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                   on_line=bgi2.append)
    eng_bgi2._register_line("3:202C:4:BGI", "流れてきた血に身体を半分浸したまま、"
                                            "じっと息を殺す。")
    eng_bgi2._register_line("4:202C:7:TextOutA", "流れき血身体半分浸しじっと息殺す")
    settle(eng_bgi2)
    check("完整版先到、缺字版后到也只翻一次",
          [row["text"] for row in bgi2]
          == ["流れてきた血に身体を半分浸したまま、じっと息を殺す。"],
          str([row["text"][:20] for row in bgi2]))
    # 同一个线程里的两句真台词（含一模一样的短句）不能被当成「缺字版」并掉
    same_thread: list[dict] = []
    eng_same = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                   on_line=same_thread.append)
    for text in ("誰か説明してほしい──", "誰か。", "誰か！！"):
        eng_same._register_line("3:202C:4:BGI", text)
    settle(eng_same)
    check("同线程的连续短句照常发射（只并完全一样的那句）",
          [row["text"] for row in same_thread] == ["誰か説明してほしい──", "誰か。"],
          str([row["text"] for row in same_thread]))
    # 噪声行只丢自己：以前一条 `─` 分隔线就会把整条线程标成「系统刷屏」，
    # 后面真正的文本全被吞掉（实测 BGI 的 TextOutA 线程就这样被误杀）
    noisy: list[dict] = []
    eng_noisy = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                    on_line=noisy.append)
    for key, text in (("gdi", "─"), ("gdi", "ؐ"), ("engine", "また一つ。"),
                      ("gdi", "視界黒塞"), ("engine", "視界を黒い何かが塞いだ。")):
        eng_noisy._register_line(key, text)
    settle(eng_noisy)
    check("两条噪声行不会把线程整体拉黑",
          [row["text"] for row in noisy] == ["また一つ。", "視界を黒い何かが塞いだ。"],
          str([row["text"][:16] for row in noisy]))
    # 反过来：真·系统刷屏线程（重复资源名 / 只喷噪声的系统线程）仍要整体丢掉
    spammy: list[dict] = []
    eng_spam = vntext.VnTextEngine(settings_getter=lambda: {"vntext_max_chars": 1200},
                                   on_line=spammy.append)
    eng_spam._register_line("sys", "10_プロローグ0725" * 6)
    for _ in range(3):
        eng_spam._register_line("menu", "セーブ")
    eng_spam._register_line("menu", "本当はこの行も出したくない訳ではない")
    settle(eng_spam)
    check("系统刷屏线程整体丢弃", spammy == []
          and eng_spam._seen.get("sys", {}).get("spam") is True,
          str([row["text"][:12] for row in spammy]))

    write("\n[引擎标识与规则集]")
    check("TVP/KIRIKIRI 规则可取出",
          vntext.profile_for("TVP/KIRIKIRI").get("collapse_doubling") is True
          and "GetTextExtentPoint32W" in vntext.profile_for("TVP/KIRIKIRI")["hook_hint"])
    check("WillPlus 规则里给出 OCR 建议",
          "OCR" in vntext.profile_for("WillPlus")["hook_hint"])
    check("未知引擎回落到 default", vntext.profile_for("不存在").get("name_prefix") is True)
    check("detect_engine 对无效 pid 不炸", vntext.detect_engine(0) == "unknown")
    # `vnreng: INSERT xxx` / `vnreng:Xxx: pattern not found` 里的引擎名要认准：
    # 以前只要看到 vnreng 就归到 TVP/KIRIKIRI，Leaf/Escu:de 都被标错
    for hint, want in (("vnreng: INSERT Leaf", "Leaf"),
                       ("vnreng: INSERT Escude", "Escu:de"),
                       ("vnreng: INSERT KiriKiriZ", "TVP/KIRIKIRI"),
                       ("vnreng: INSERT Siglus", "Siglus"),
                       ("vnreng: INSERT CatSystem2", "CatSystem2/Ares"),
                       ("vnreng:WillPlusW: pattern not found", "WillPlus")):
        eng_hint = vntext.VnTextEngine(settings_getter=lambda: {}, on_line=lambda row: None)
        eng_hint._note_engine_hint(hint)
        check(f"引擎名识别：{hint[:26]}", eng_hint._engine == want, eng_hint._engine)

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
    # Windows 报的语言标签是 ja，我们请求的是 ja-JP —— 只比字符串会把装了日语 OCR
    # 的机器误判成没装（实测踩过），这里锁住子标签匹配的行为
    saved_langs = ocr._langs
    try:
        ocr._langs = ("en-US", "ja", "zh-Hans-CN")
        check("ja-JP 能匹配到系统的 ja", ocr.has_language("ja-JP") and ocr.real_tag("ja-JP") == "ja")
        ocr._langs = ("en-US", "zh-Hans-CN")
        check("没装日语时不误报", not ocr.has_language("ja-JP"))
    finally:
        ocr._langs = saved_langs
    check("OCR 逐字空格被去掉",
          vntext.tidy_ocr_text("出 会 っ て 、 A B") == "出会って 、 A B",
          vntext.tidy_ocr_text("出 会 っ て 、 A B"))
    # OCR 每 0.9 秒抓一屏，同一句不能反复送翻译
    ocr_lines: list[str] = []
    eng_ocr = vntext.VnTextEngine(settings_getter=lambda: {}, on_line=ocr_lines.append)
    same = "なにより 、 初めて 。 対戦する相手であろうと 、 一切の手心を加えるつもりのない気概 。"
    for _ in range(4):
        eng_ocr._emit(same, "ocr")
    check("同一屏 OCR 只翻一次", len(ocr_lines) == 1, f"发出 {len(ocr_lines)} 条")

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
