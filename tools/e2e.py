"""端到端自检：空状态 -> 导入 -> 自动联网搜索 -> 切换背景 -> 启动/结束进程。"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import json
import shutil
import sys
import threading
import time
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox"
TEST_DATA = SANDBOX / "e2e-data"
EXE_DIR = SANDBOX / "e2e-games" / "ELDEN RING" / "Game"

import os  # noqa: E402

os.environ["AURORA_DATA"] = str(TEST_DATA)

import webview  # noqa: E402

import main as app_main  # noqa: E402
from gl.api import Api  # noqa: E402

OUT = Path(__file__).resolve().parent / "e2e-report.json"
results: list[dict] = []

FAKE_TEXTTRACTOR = '''"""端到端自检用的假 TextractorCLI。"""
import sys, time

def emit(handle, name, code, text):
    line = f"[{handle}:000004D2:00000000:0:0:{name}:{code}] {text}\\n"
    sys.stdout.buffer.write(line.encode("utf-16-le"))
    sys.stdout.buffer.flush()

while True:
    raw = sys.stdin.buffer.readline()
    if not raw:
        break
    cmd = raw.decode("utf-16-le", "ignore").strip()
    if cmd.startswith("attach"):
        emit("00000001", "menu", "HS1@0", "セーブ")
        for text in ["彼女は静かに微笑んだ。", "「また明日ね」と小さく呟いて、"]:
            emit("00000002", "dialogue", "HS2@0", text)
            time.sleep(0.05)
    elif cmd.startswith("detach"):
        break
'''

FAKE_TRANSLATOR = '''"""端到端自检用的假翻译引擎插件（P6.4）。"""

class Plugin:
    id = "e2e-trans"
    name = "E2E 翻译"
    requires_key = False
    supports_stream = True

    def translate(self, text, *, context, target, glossary, on_delta):
        out = "【插件】" + str(text)[:24]
        if on_delta:
            on_delta(out)
        return {"text": out, "provider": "e2e-trans"}
'''


def write_plugin_fixtures(data_dir: Path) -> None:
    """两个假插件：一个能用的翻译引擎 + 一个版本不兼容的（界面必须写出原因）。"""
    translators = data_dir / "plugins" / "translators"
    good = translators / "e2e-trans"
    good.mkdir(parents=True, exist_ok=True)
    (good / "plugin.json").write_text(json.dumps({
        "api_version": "1.0", "kind": "translator", "id": "e2e-trans",
        "name": "E2E 翻译", "version": "0.1.0", "entry": "main.py",
        "author": "e2e", "permissions": ["network"],
    }, ensure_ascii=False), encoding="utf-8")
    (good / "main.py").write_text(FAKE_TRANSLATOR, encoding="utf-8")

    bad = translators / "e2e-bad"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "plugin.json").write_text(json.dumps({
        "api_version": "2.0", "kind": "translator", "id": "e2e-bad",
        "name": "E2E 旧版插件", "version": "0.1.0", "entry": "main.py",
    }, ensure_ascii=False), encoding="utf-8")


class MockLLM(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()
        for piece in ("她静", "静地", "微笑了。"):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):
        return


def step(name: str, ok: bool, detail="", skipped: bool = False):
    results.append({"step": name, "ok": bool(ok), "skipped": skipped, "detail": detail})
    tag = "SKIP" if skipped else ("PASS" if ok else "FAIL")
    print(f"  {tag} " + name + (f"  {detail}" if detail else ""))


def probe(window, js: str):
    raw = window.evaluate_js(f"(() => {{ {js} }})()")
    try:
        return json.loads(raw)
    except Exception:
        return raw


def main() -> int:
    if TEST_DATA.exists():
        shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)
    EXE_DIR.mkdir(parents=True, exist_ok=True)
    fake_cli = SANDBOX / "e2e-textractor.py"
    fake_cli.write_text(FAKE_TEXTTRACTOR, encoding="utf-8")
    write_plugin_fixtures(TEST_DATA)
    llm = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockLLM)
    threading.Thread(target=llm.serve_forever, daemon=True).start()
    llm_port = llm.server_address[1]
    exe = EXE_DIR / "eldenring.exe"
    if not exe.exists():
        shutil.copy2(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "ping.exe", exe)

    api = Api()
    window = app_main.build_window(api)
    api._window = window

    def run() -> None:
        time.sleep(6)

        def real_click(selector: str):
            """像真人一样点：按坐标找 elementFromPoint 命中的元素再派发鼠标事件。

            直接用 element.click() 会绕过遮挡，曾经因此漏掉「设置页返回按钮被工具条盖住」
            这种问题，所以关键点击一律走这里。
            """
            return probe(window, """
              const node = document.querySelector('%s');
              const r = node.getBoundingClientRect();
              const x = Math.round(r.left + r.width / 2);
              const y = Math.round(r.top + r.height / 2);
              const target = document.elementFromPoint(x, y) || node;
              for (const type of ['mousedown', 'mouseup', 'click']) {
                target.dispatchEvent(new MouseEvent(type,
                  {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0}));
              }
              return JSON.stringify({
                hits: !!(target.closest && target.closest('%s')),
                top: target.id || target.className || target.tagName,
                at: [x, y]});
            """ % (selector, selector))

        try:
            # 1. 空状态
            state = probe(window, """
              const e = document.getElementById('empty'), v = document.getElementById('view');
              return JSON.stringify({empty: !e.hidden, view: !v.hidden,
                                     list: document.querySelectorAll('.gi').length});
            """)
            step("空库显示空状态", state.get("empty") and not state.get("view") and state.get("list") == 0, state)

            # 2. 导入 + 自动搜索
            res = api.add_by_path(str(exe))
            step("导入可执行文件", bool(res.get("ok")), res.get("game", {}).get("name"))
            game_id = res["game"]["id"]

            deadline = time.time() + 90
            state = {}
            while time.time() < deadline:
                time.sleep(2)
                state = probe(window, f"""
                  const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                  const on = a.classList.contains('on') ? a : b;
                  const inner = on.querySelector('.bg-img');
                  return JSON.stringify({{
                    list: document.querySelectorAll('.gi').length,
                    cover: (() => {{ const i = document.querySelector('.gi-cover img');
                                     return i ? i.naturalWidth : 0; }})(),
                    title: (document.getElementById('gTitle')||{{}}).textContent,
                    desc: (document.getElementById('gDesc')||{{}}).textContent.slice(0,40),
                    chips: document.querySelectorAll('.chip').length,
                    bg: inner ? getComputedStyle(inner).backgroundImage.slice(0,60) : '',
                    logo: (document.getElementById('gLogo')||{{}}).naturalWidth || 0,
                    fetching: !(document.getElementById('fetching')||{{hidden:true}}).hidden,
                  }});
                """)
                if (state.get("title") and state["title"] not in ("—", "") and not state.get("fetching")):
                    break

            # LOGO 是独立请求，单独多等一会儿
            logo_deadline = time.time() + 25
            while time.time() < logo_deadline and not state.get("logo"):
                time.sleep(2)
                state["logo"] = probe(window,
                    "return String((document.getElementById('gLogo')||{}).naturalWidth || 0);")

            # 封面缩略图也要等一等
            cover_deadline = time.time() + 20
            while time.time() < cover_deadline and not state.get("cover"):
                time.sleep(2)
                state["cover"] = probe(window,
                    "const i = document.querySelector('.gi-cover img'); return i ? i.naturalWidth : 0;")

            game = api._library.get(game_id)
            net_down = game.get("metadata_state") != "ok" and "网络" in (game.get("metadata_note") or "")
            note = "网络不可用，跳过联网相关检查" if net_down else ""

            step("自动搜索并填充界面", bool(state.get("title")) and state["title"] != "—",
                 state.get("title") or note, skipped=net_down)
            step("界面显示简介", len(state.get("desc") or "") > 5, state.get("desc"), skipped=net_down)
            step("界面显示标签", (state.get("chips") or 0) >= 2, f"{state.get('chips')} chips",
                 skipped=net_down)

            bg_deadline = time.time() + 20
            while time.time() < bg_deadline and "url(" not in (state.get("bg") or ""):
                time.sleep(2)
                state["bg"] = probe(window, """
                  const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                  const on = a.classList.contains('on') ? a : b;
                  const inner = on.querySelector('.bg-img');
                  return inner ? String(getComputedStyle(inner).backgroundImage).slice(0, 60) : '';
                """)
            step("背景图已应用", "url(" in (state.get("bg") or ""), state.get("bg"), skipped=net_down)
            step("LOGO 已加载", (state.get("logo") or 0) > 0, f"{state.get('logo')}px", skipped=net_down)
            step("大厅封面图已加载", (state.get("cover") or 0) > 0, f"{state.get('cover')}px",
                 skipped=net_down)

            # 3. 背景切换
            images = game.get("images") or []
            step("获得多张背景候选", len(images) >= 3, f"{len(images)} 张", skipped=net_down)
            if len(images) >= 2:
                target = images[1]["url"]
                api.set_background(game_id, target, images[1]["kind"])
                time.sleep(4)
                state = probe(window, """
                  const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                  const on = a.classList.contains('on') ? a : b;
                  const inner = on.querySelector('.bg-img');
                  return JSON.stringify({bg: inner ? getComputedStyle(inner).backgroundImage.slice(0,90) : '',
                                         opacity: getComputedStyle(on).opacity});
                """)
                step("切换背景生效", target.split("/")[-1] in (state.get("bg") or "")
                     and float(state.get("opacity") or 0) > 0.95, state)

                # 背景缩放：只由背景面板的滑杆控制
                window.evaluate_js("""
                  (() => {
                    const s = document.getElementById('bgZoom');
                    s.value = 180;
                    s.dispatchEvent(new Event('input', {bubbles: true}));
                    s.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'zoom';
                  })()
                """)
                time.sleep(1.4)
                zoomed = probe(window, f"""
                  const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                  const on = a.classList.contains('on') ? a : b;
                  return JSON.stringify({{transform: on.style.transform,
                                          scale: {api._library.get(game_id).get('bg_scale') or 1},
                                          slider: document.getElementById('bgZoom').value}});
                """)
                step("缩放滑杆生效", float(zoomed.get("scale") or 1) > 1.5 and "scale" in
                     (zoomed.get("transform") or ""), zoomed)

                window.evaluate_js("document.getElementById('bgViewReset').click()")
                time.sleep(1.4)
                reset = probe(window, """
                  const a = document.getElementById('bg-a'), b = document.getElementById('bg-b');
                  const on = a.classList.contains('on') ? a : b;
                  return JSON.stringify({transform: on.style.transform});
                """)
                step("背景缩放复位", not (reset.get("transform") or ""), reset)

            # 3.5 大厅导航（封面环形队列）
            hall = probe(window, """
              const tiles = [...document.querySelectorAll('#hallRow .gi')]
                .filter((n) => n.style.transform)
                .map((n) => {
                  const r = n.getBoundingClientRect();
                  return {key: n.dataset.id || 'add',
                          deg: Number((n.style.transform.match(/rotateY\\((-?[\\d.]+)deg/) || [0, 0])[1]),
                          h: Math.round(r.height),
                          cx: Math.round(r.x + r.width / 2)};
                });
              const front = tiles.find((t) => t.deg === 0) || {};
              return JSON.stringify({
                tiles: document.querySelectorAll('#hallRow .gi').length,
                add: !!document.querySelector('#hallRow .gi-add'),
                focus: document.getElementById('hallName').textContent,
                cx: front.cx || 0,
                vw: innerWidth,
                visible: tiles,
                ring: window.__aurora.ring(),
                getHit: (() => { const b = document.getElementById('btnGetGames');
                                 const r = b.getBoundingClientRect();
                                 const el = document.elementFromPoint(
                                   Math.round(r.left + r.width / 2),
                                   Math.round(r.top + r.height / 2));
                                 return !!(el && el.closest('#btnGetGames')); })(),
              });
            """)
            step("大厅出现封面块", hall.get("tiles") == 2 and hall.get("add"), hall)
            step("大厅「获取游戏」入口可点（没被工具条压住）", bool(hall.get("getHit")), hall.get("getHit"))
            step("焦点封面居中", abs((hall.get("cx") or 0) - (hall.get("vw") or 0) / 2) <= 3,
                 f"cx={hall.get('cx')} vw={hall.get('vw')}")

            key = ("const k='%s'; document.dispatchEvent("
                   "new KeyboardEvent('keydown',{key:k,bubbles:true})); return 1;")

            # 环形队列的空间感：焦点最大，越远越小、越斜
            visible = sorted(hall.get("visible") or [], key=lambda t: abs(t["deg"]))
            heights = [t["h"] for t in visible]
            tilted = [t["deg"] for t in visible if t["deg"]]
            step("焦点封面最大，越远越小",
                 len(heights) >= 2 and all(a >= b for a, b in zip(heights, heights[1:])),
                 str(heights))
            step("非焦点封面向竖轴倾斜",
                 bool(tilted) and all(abs(d) >= 8 for d in tilted),
                 str([t["deg"] for t in visible]))

            # 循环队列：在第一张按 ← 绕到最后一张（＋ 导入游戏），再按 → 回到开头
            ring_keys = (hall.get("ring") or {}).get("keys") or []
            window.evaluate_js("(() => { %s })()" % (key % "Home"))
            time.sleep(0.9)
            first_item = probe(window, "return JSON.stringify(window.__aurora.ring());")
            window.evaluate_js("(() => { %s })()" % (key % "ArrowLeft"))
            time.sleep(0.9)
            looped = probe(window, "return JSON.stringify(window.__aurora.ring());")
            step("首尾相接：← 从第一张绕到最后一张",
                 bool(ring_keys) and first_item.get("focus") == ring_keys[0]
                 and looped.get("focus") == ring_keys[-1]
                 # 只走一步（走最近的那一边），而不是绕一整圈
                 and abs(looped.get("float", 0) - first_item.get("float", 0)) <= 1.5,
                 f"{first_item.get('focus')} -> {looped.get('focus')} "
                 f"float {first_item.get('float')} -> {looped.get('float')}")
            window.evaluate_js("(() => { %s })()" % (key % "ArrowRight"))
            time.sleep(0.9)
            step("首尾相接：→ 从最后一张绕回第一张",
                 (probe(window, "return JSON.stringify(window.__aurora.ring());")
                  .get("focus") == (ring_keys[0] if ring_keys else None)),
                 f"keys={len(ring_keys)}")

            window.evaluate_js("(() => { %s })()" % (key % "ArrowRight"))
            time.sleep(1.0)
            moved = probe(window, "return JSON.stringify({focus: document.getElementById('hallName').textContent});")
            window.evaluate_js("(() => { %s })()" % (key % "ArrowLeft"))
            time.sleep(1.0)
            back_hall = probe(window, "return JSON.stringify({focus: document.getElementById('hallName').textContent});")
            step("方向键切换封面",
                 moved.get("focus") != back_hall.get("focus")
                 and back_hall.get("focus") == game.get("name"),
                 f"{moved.get('focus')} -> {back_hall.get('focus')}")

            # 3.6 主页布局可切换：环形队列 ↔ 平铺横滑（NS 大厅）
            def set_layout(value):
                window.evaluate_js("""(() => {
                  const sel = document.getElementById('setHallLayout');
                  sel.value = %s;
                  sel.dispatchEvent(new Event('change'));
                })()""" % json.dumps(value))
                time.sleep(1.3)
                return probe(window, "return JSON.stringify(window.__aurora.layout());")

            flat = set_layout("flat")
            focused_tile = next((t for t in flat.get("tiles") or [] if t.get("focus")), None)
            step("切到平铺横滑：一行排开、焦点居中",
                 flat.get("name") == "flat" and flat.get("flatClass")
                 and focused_tile is not None
                 and abs(focused_tile["center"] - flat["viewportWidth"] / 2) <= 40
                 and all(t["visible"] for t in flat["tiles"])
                 and all("matrix3d" not in (t["transform"] or "") for t in flat["tiles"]),
                 f"{flat.get('name')} center={focused_tile and focused_tile['center']} "
                 f"vw={flat.get('viewportWidth')} 可见={sum(1 for t in flat['tiles'] if t['visible'])}"
                 f"/{len(flat['tiles'])}")
            window.evaluate_js("(() => { %s })()" % (key % "Home"))
            time.sleep(0.9)
            head = probe(window, "return JSON.stringify(window.__aurora.ring());")
            window.evaluate_js("(() => { %s })()" % (key % "ArrowLeft"))
            time.sleep(0.9)
            step("平铺布局不循环：第一张再按 ← 仍是第一张",
                 bool(head.get("focus"))
                 and (probe(window, "return JSON.stringify(window.__aurora.ring());")
                      .get("focus") == head.get("focus")),
                 f"{head.get('focus')}")

            ring_back = set_layout("ring")
            step("切回环形队列：class 去掉、封面重新绕轴排开",
                 ring_back.get("name") == "ring" and not ring_back.get("flatClass")
                 and any("matrix3d" in (t["transform"] or "")
                         for t in ring_back.get("tiles") or []),
                 f"{ring_back.get('name')}")

            window.evaluate_js(
                "document.getElementById('app').dispatchEvent("
                "new WheelEvent('wheel',{deltaY:120,bubbles:true,cancelable:true}));")
            time.sleep(1.0)
            wheeled = probe(window, "return JSON.stringify({focus: document.getElementById('hallName').textContent});")
            step("滚轮切换封面", wheeled.get("focus") != back_hall.get("focus"), wheeled)
            window.evaluate_js("(() => { %s })()" % (key % "ArrowLeft"))
            time.sleep(1.0)

            # 横向拖动换封面之后，单击封面必须还能进游戏页（拖拽标志位不能留在按下状态）
            window.evaluate_js("(() => { %s })()" % (key % "Home"))
            time.sleep(0.8)
            dragged = probe(window, """
              // 找一个封面之间、又不是拖窗口区域的空位，像真人那样在这里按下起手
              const vp = document.getElementById('hallViewport').getBoundingClientRect();
              let pt = null;
              for (let y = vp.top + 16; y < vp.bottom - 16 && !pt; y += 14) {
                for (let x = vp.left + 16; x < vp.right - 16; x += 14) {
                  const el = document.elementFromPoint(x, y);
                  if (!el || el.closest('.gi') || el.closest('[data-drag]') || el.closest('.get-pill')) continue;
                  pt = [Math.round(x), Math.round(y)];
                  break;
                }
              }
              if (!pt) return JSON.stringify({error: 'no-empty-spot'});
              const before = document.getElementById('hallName').textContent;
              const fire = (node, type, x, y) => node.dispatchEvent(new MouseEvent(type,
                {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0}));
              // 拖过一张多一点：环形队列是循环的，拖太远会绕回原处
              fire(document.elementFromPoint(pt[0], pt[1]), 'mousedown', pt[0], pt[1]);
              fire(document, 'mousemove', pt[0] - 120, pt[1]);
              fire(document, 'mouseup', pt[0] - 120, pt[1]);
              return JSON.stringify({error: '', before: before, pt: pt});
            """)
            time.sleep(0.8)
            swiped = probe(window, """return JSON.stringify({focus: document.getElementById('hallName').textContent});""")
            step("鼠标横向拖动切换封面",
                 not dragged.get("error") and dragged.get("before") != swiped.get("focus"),
                 f"{dragged.get('before')} -> {swiped.get('focus')} {dragged.get('error') or ''}")

            # 拖动后可能停在末尾的「＋」方块上，所以明确点一张游戏封面
            target = probe(window, """
              const t = document.querySelector('#hallRow .gi[data-id]');
              return JSON.stringify({name: t.getAttribute('title'), id: t.dataset.id});
            """)
            hit = real_click("#hallRow .gi[data-id]")
            time.sleep(1.2)
            after_drag_click = probe(window, """
              return JSON.stringify({view: !document.getElementById('view').hidden,
                                     title: document.getElementById('gTitle').textContent});
            """)
            step("拖动换封面后单击封面仍能进入游戏页",
                 not dragged.get("error") and dragged.get("before") != swiped.get("focus")
                 and (hit or {}).get("hits") and after_drag_click.get("view")
                 and after_drag_click.get("title") == target.get("name"), after_drag_click)
            window.evaluate_js("(() => { %s })()" % (key % "Escape"))
            time.sleep(1.0)
            window.evaluate_js("(() => { %s })()" % (key % "Home"))   # 焦点回到第一个游戏
            time.sleep(0.8)

            hit_enter = real_click("#hallRow .gi.focus")
            time.sleep(1.2)
            entered = probe(window, """
              return JSON.stringify({hall: document.getElementById('hall').hidden,
                                     view: !document.getElementById('view').hidden,
                                     title: document.getElementById('gTitle').textContent,
                                     back: !document.getElementById('btnBack').hidden,
                                     backHit: (() => {
                                       const b = document.getElementById('btnBack');
                                       const r = b.getBoundingClientRect();
                                       const el = document.elementFromPoint(
                                         Math.round(r.left + r.width / 2),
                                         Math.round(r.top + r.height / 2));
                                       return !!(el && el.closest('#btnBack')); })()});
            """)
            step("单击封面进入游戏页（按坐标命中）",
                 (hit_enter or {}).get("hits") and entered.get("hall") and entered.get("view")
                 and entered.get("back") and entered.get("backHit")
                 and entered.get("title") == game.get("name"), entered)

            window.evaluate_js("(() => { %s })()" % (key % "Escape"))
            time.sleep(1.2)
            escaped = probe(window, """
              return JSON.stringify({hall: !document.getElementById('hall').hidden,
                                     view: document.getElementById('view').hidden});
            """)
            step("Esc 返回大厅", escaped.get("hall") and escaped.get("view"), escaped)

            # 3.7 获取游戏（下载大厅）
            window.evaluate_js("document.querySelector('#hallRow .gi-add').click()")
            time.sleep(1.0)
            add_menu = probe(window, """
              const m = document.getElementById('addMenu');
              return JSON.stringify({open: !m.hidden,
                                     items: [...m.querySelectorAll('button')].map(b => b.textContent.trim())});
            """)
            step("末尾方块弹出二选一菜单",
                 add_menu.get("open") and len(add_menu.get("items") or []) == 2, add_menu)

            window.evaluate_js(
                "document.querySelector('#addMenu [data-add-act=get]').click()")
            time.sleep(2.0)
            get_panel = probe(window, """
              const p = document.getElementById('getPanel');
              const r = p.getBoundingClientRect();
              return JSON.stringify({open: p.classList.contains('open'),
                                     dir: document.getElementById('getDir').textContent,
                                     watch: document.getElementById('getWatch').checked,
                                     sites: document.querySelectorAll('#getSites .link-chip').length,
                                     inside: r.bottom <= innerHeight + 1 && r.top >= 0});
            """)
            step("下载大厅面板打开且不溢出",
                 get_panel.get("open") and get_panel.get("inside")
                 and get_panel.get("sites", 0) >= 3
                 and bool(get_panel.get("dir")), get_panel)

            # 资源站：加一个再删掉
            window.evaluate_js("document.getElementById('getAddSite').click()")
            time.sleep(0.6)
            window.evaluate_js("""
              document.getElementById('getSiteName').value = 'E2E 测试站';
              document.getElementById('getSiteUrl').value = 'https://example.com/search?q={query}';
              document.getElementById('getSiteSave').click();
            """)
            time.sleep(1.6)
            sites_after_add = probe(window, """
              return JSON.stringify({names: [...document.querySelectorAll('#getSites .link-chip')]
                                               .map(b => b.textContent.trim()),
                                     formHidden: document.getElementById('getSiteForm').hidden});
            """)
            step("能新增资源站",
                 "E2E 测试站" in (sites_after_add.get("names") or [])
                 and sites_after_add.get("formHidden"), sites_after_add)

            window.evaluate_js("""
              const chip = [...document.querySelectorAll('#getSites .site-chip')]
                .find(c => c.textContent.includes('E2E 测试站'));
              if (chip) chip.querySelector('.site-del').click();
            """)
            time.sleep(1.4)
            sites_after_del = probe(window, """
              return JSON.stringify({names: [...document.querySelectorAll('#getSites .link-chip')]
                                               .map(b => b.textContent.trim())});
            """)
            step("能删除资源站",
                 "E2E 测试站" not in (sites_after_del.get("names") or [])
                 and len(sites_after_del.get("names") or []) >= 3, sites_after_del)

            target_dir = SANDBOX / "e2e-downloads"
            target_dir.mkdir(parents=True, exist_ok=True)
            saved = api.set_download_option("download_dir", str(target_dir))
            reloaded_dir = api._library.settings.get("download_dir")
            window.evaluate_js(
                "document.getElementById('getPanel').classList.remove('open')")
            step("下载目录设置已持久化",
                 bool(saved.get("ok")) and str(reloaded_dir) == str(target_dir), str(reloaded_dir))
            api.set_download_option("download_dir", str(TEST_DATA / "downloads"))

            # 3.8 设置页：整页 + 八个页签
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.5)
            settings = probe(window, """
              const v = document.getElementById('settingsView');
              const r = v.getBoundingClientRect();
              return JSON.stringify({
                open: !v.hidden,
                tabs: [...v.querySelectorAll('#setNav .set-tab')].map(t => t.dataset.pane),
                panes: [...v.querySelectorAll('.set-pane')].map(p => p.dataset.pane),
                on: (v.querySelector('.set-pane.on') || {}).dataset?.pane,
                hallHidden: document.getElementById('hall').hidden,
                inside: r.bottom <= innerHeight + 1 && r.top >= -1 && r.right <= innerWidth + 1});
            """)
            step("设置页能打开且盖住大厅",
                 settings.get("open") and settings.get("hallHidden")
                 and len(settings.get("tabs") or []) == 8
                 and settings.get("tabs") == settings.get("panes")
                 and settings.get("inside"), settings)

            # 3.8b 插件区（P6.4 / ADR-0009）：状态、权限、来源与「重新扫描」
            window.evaluate_js(
                "document.querySelector('#setNav .set-tab[data-pane=plugins]').click()")
            time.sleep(1.4)
            plugins_pane = probe(window, """
              const pane = document.querySelector('#settingsView .set-pane.on');
              const rows = [...document.querySelectorAll('#pluginList .plugin-row')];
              const text = rows.map((r) => r.textContent.replace(/\\s+/g, ' ').trim()).join(' | ');
              return JSON.stringify({
                pane: pane && pane.dataset.pane,
                count: rows.length,
                text: text,
                dir: document.getElementById('pluginDir').textContent,
                providers: [...document.getElementById('setTransProvider').options]
                             .map((o) => o.value)});
            """)
            step("设置页插件区列出状态 / 权限 / 来源（中文标签）",
                 plugins_pane.get("pane") == "plugins"
                 and plugins_pane.get("count") == 2
                 and "E2E 翻译" in (plugins_pane.get("text") or "")
                 and "正常" in (plugins_pane.get("text") or "")
                 and "版本不兼容" in (plugins_pane.get("text") or "")
                 and "权限：" in (plugins_pane.get("text") or "")
                 and "plugins" in (plugins_pane.get("dir") or ""),
                 f"{plugins_pane.get('count')} 个插件 / {plugins_pane.get('dir')}")
            step("翻译方式下拉里有插件引擎（plugin:e2e-trans）",
                 "plugin:e2e-trans" in (plugins_pane.get("providers") or []),
                 plugins_pane.get("providers"))

            window.evaluate_js("document.getElementById('btnPluginRescan').click()")
            time.sleep(1.6)
            rescanned = probe(window, """
              return JSON.stringify({
                count: document.querySelectorAll('#pluginList .plugin-row').length,
                toast: document.getElementById('toast').textContent});
            """)
            step("「重新扫描插件」刷新列表并给出回执",
                 rescanned.get("count") == 2
                 and "已重新扫描插件" in (rescanned.get("toast") or ""), rescanned)

            # 3.8c 翻译引擎插件真的接进简介链路（provider = plugin:<id>）
            before_plug = api._library.get(game_id)
            saved_desc = {key: before_plug.get(key) for key in
                          ("description", "description_original",
                           "description_translated", "description_lang")}
            saved_provider = api._library.settings.get("translate_provider")
            api._library.set_setting("translate_provider", "plugin:e2e-trans")
            api._library.update(game_id,
                                description=("The story follows a young swordsman "
                                             "who must protect his hometown."),
                                description_original="", description_translated="")
            plug_res = api._translation._translate_description(game_id)
            step("简介翻译能走插件引擎（provider = plugin:e2e-trans）",
                 plug_res.get("provider") == "plugin:e2e-trans" and plug_res.get("changed"),
                 plug_res)
            api._library.set_setting("translate_provider", saved_provider or "auto")
            api._library.update(game_id, **saved_desc)

            # 3.8d 关于页 → 导出诊断包（P7）：zip 真的落盘，页面显示路径
            window.evaluate_js(
                "document.querySelector('#setNav .set-tab[data-pane=about]').click()")
            time.sleep(1.0)
            has_diag_btn = probe(window,
                "return String(!!document.getElementById('btnDiagnostics'));")
            window.evaluate_js("document.getElementById('btnDiagnostics').click()")
            diag_hint = ""
            for _ in range(12):
                time.sleep(1.0)
                diag_hint = probe(window,
                    "return document.getElementById('diagHint').textContent;")
                if isinstance(diag_hint, str) and "已导出" in diag_hint:
                    break
            diag_zips = sorted((TEST_DATA / "diagnostics").glob("*.zip"))
            step("关于页能导出诊断包（zip 落盘 + 页面显示路径）",
                 str(has_diag_btn).lower() == "true" and "已导出" in (diag_hint or "")
                 and len(diag_zips) == 1 and diag_zips[0].stat().st_size > 0,
                 f"{len(diag_zips)} 个 zip / {(diag_hint or '')[:60]}")

            # 3.9 网络页：控件读到状态，测试按钮能出结果
            window.evaluate_js(
                "document.querySelector('#setNav .set-tab[data-pane=net]').click()")
            time.sleep(1.0)
            tab_net = probe(window, """
              const on = document.querySelector('#settingsView .set-pane.on');
              return JSON.stringify({
                pane: on && on.dataset.pane,
                mode: document.getElementById('setProxyMode').value,
                fallback: document.getElementById('setProxyFallback').checked,
                status: document.getElementById('netStatus').textContent});
            """)
            step("设置页能切到网络页并读到代理状态",
                 tab_net.get("pane") == "net"
                 and tab_net.get("mode") in ("auto", "direct", "manual")
                 and "当前生效" in (tab_net.get("status") or ""), tab_net)

            window.evaluate_js("document.getElementById('netTest').click()")
            rows_n = 0
            for _ in range(30):
                time.sleep(1.0)
                rows_n = probe(window,
                               "return document.querySelectorAll('#netResults .net-line').length;")
                if isinstance(rows_n, int) and rows_n >= 5:
                    break
            step("网络测试按钮列出五个端点", isinstance(rows_n, int) and rows_n >= 5,
                 f"{rows_n} 行", skipped=net_down)

            # 3.10 转区页：未装 LE 也要能显示状态、不抛错
            window.evaluate_js(
                "document.querySelector('#setNav .set-tab[data-pane=locale]').click()")
            time.sleep(1.6)
            tab_locale = probe(window, """
              const on = document.querySelector('#settingsView .set-pane.on');
              return JSON.stringify({
                pane: on && on.dataset.pane,
                status: document.getElementById('leStatus').textContent,
                path: document.getElementById('setLePath').value,
                def: document.getElementById('setLocaleDefault').checked,
                download: !!document.getElementById('setLeDownload')});
            """)
            step("设置页能切到转区页（未装 LE 也不报错）",
                 tab_locale.get("pane") == "locale"
                 and bool(tab_locale.get("status"))
                 and "正在检测" not in (tab_locale.get("status") or "")
                 and "失败" not in (tab_locale.get("status") or "")
                 and tab_locale.get("download"), tab_locale)

            # 设置页里的滚轮 / 方向键 / 回车不能穿透到大厅（否则背景会跟着换，甚至启动游戏）
            SCOPE = """
              const on = document.getElementById('bg-a').classList.contains('on')
                ? document.getElementById('bg-a') : document.getElementById('bg-b');
              const inner = on.querySelector('.bg-img');
              return JSON.stringify({
                settings: !document.getElementById('settingsView').hidden,
                focus: document.getElementById('hallName').textContent,
                bg: inner ? getComputedStyle(inner).backgroundImage.slice(0, 90) : ''});
            """
            scope_before = probe(window, SCOPE)
            window.evaluate_js("""
              const pane = document.querySelector('#settingsView .set-pane.on');
              pane.dispatchEvent(new WheelEvent('wheel',
                {deltaY: 120, deltaX: 0, bubbles: true, cancelable: true}));
              for (const k of ['ArrowRight', 'ArrowLeft', 'Home', 'End', 'Enter']) {
                document.dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true}));
              }
            """)
            time.sleep(1.6)
            scope_after = probe(window, SCOPE)
            step("设置页里滚轮 / 方向键 / 回车不改大厅状态",
                 scope_after.get("settings")
                 and scope_before.get("focus") == scope_after.get("focus")
                 and scope_before.get("bg") == scope_after.get("bg")
                 and not api._pm.is_running(game_id),
                 f"{scope_before.get('focus')} -> {scope_after.get('focus')}"
                 f" / 进程运行中={api._pm.is_running(game_id)}")

            window.evaluate_js(
                "document.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'Escape',bubbles:true}))")
            time.sleep(1.3)
            back_hall = probe(window, """
              return JSON.stringify({
                settings: !document.getElementById('settingsView').hidden,
                hall: !document.getElementById('hall').hidden,
                focus: (document.querySelector('#hallRow .gi.focus') || {}).dataset?.id});
            """)
            step("Esc 关设置回大厅且焦点没变",
                 (not back_hall.get("settings")) and back_hall.get("hall")
                 and back_hall.get("focus") == game_id, back_hall)

            # 鼠标退出设置：返回按钮不能被工具条盖住，齿轮也要能开能关
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.5)
            win_btns = probe(window, """
              const hit = (id) => {
                const b = document.getElementById(id);
                const r = b.getBoundingClientRect();
                const el = document.elementFromPoint(Math.round(r.left + r.width / 2),
                                                    Math.round(r.top + r.height / 2));
                return !!(el && el.closest('#' + id));
              };
              return JSON.stringify({min: hit('btnMin'), close: hit('btnClose')});
            """)
            back_hit = real_click("#setBack")
            time.sleep(1.3)
            after_back = probe(window, """
              return JSON.stringify({settings: !document.getElementById('settingsView').hidden,
                                     hall: !document.getElementById('hall').hidden});
            """)
            step("鼠标点「← 返回」能退出设置（按钮不被工具条遮挡）",
                 (back_hit or {}).get("hits") and win_btns.get("min") and win_btns.get("close")
                 and (not after_back.get("settings")) and after_back.get("hall"),
                 {"hit": back_hit, "win": win_btns, "after": after_back})

            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.4)
            gear_open = probe(window, """
              return JSON.stringify({
                settings: !document.getElementById('settingsView').hidden,
                on: document.getElementById('btnSettings').classList.contains('on'),
                searchHidden: getComputedStyle(
                  document.querySelector('#toolbar .search')).display === 'none'});
            """)
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.3)
            gear_closed = probe(window, """
              return JSON.stringify({settings: !document.getElementById('settingsView').hidden,
                                     searchHidden: getComputedStyle(
                                       document.querySelector('#toolbar .search')).display === 'none',
                                     hall: !document.getElementById('hall').hidden});
            """)
            step("齿轮能开也能关，设置态收起搜索与排序",
                 gear_open.get("settings") and gear_open.get("on") and gear_open.get("searchHidden")
                 and (not gear_closed.get("settings")) and (not gear_closed.get("searchHidden"))
                 and gear_closed.get("hall"),
                 {"open": gear_open, "closed": gear_closed})

            # 设置页期间后台搜索结束：只提示一句，不能把候选面板盖到设置页上
            real_click("#hallRow .gi[data-id]")
            time.sleep(1.3)
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.5)
            window.evaluate_js("""
              window.__aurora.emit('metadata:notfound', {id: '%s', note: '没有找到匹配结果',
                                                         candidates: [], quiet: false});
            """ % game_id)
            time.sleep(1.2)
            panel_scope = probe(window, """
              return JSON.stringify({
                settings: !document.getElementById('settingsView').hidden,
                match: document.getElementById('matchPanel').classList.contains('open'),
                body: !document.getElementById('view').hidden});
            """)
            step("设置页期间搜索结束不把面板盖上来",
                 panel_scope.get("settings") and not panel_scope.get("match"), panel_scope)
            window.evaluate_js("(() => { %s })()" % (key % "Escape"))
            time.sleep(1.2)
            window.evaluate_js("(() => { %s })()" % (key % "Escape"))
            time.sleep(1.2)
            closed_again = probe(window, """
              return JSON.stringify({hall: !document.getElementById('hall').hidden,
                                     view: document.getElementById('view').hidden,
                                     match: document.getElementById('matchPanel').classList.contains('open')});
            """)
            step("连按 Esc：先关设置再回大厅",
                 closed_again.get("hall") and closed_again.get("view")
                 and not closed_again.get("match"), closed_again)

            # 3.12 分类工作区
            window.evaluate_js("document.querySelector('.vs-btn[data-view=categories]').click()")
            time.sleep(1.8)
            cat_open = probe(window, """
              const v = document.getElementById('categoriesView');
              const r = v.getBoundingClientRect();
              return JSON.stringify({open: !v.hidden, hall: document.getElementById('hall').hidden,
                                     title: document.getElementById('catTitle').textContent,
                                     cards: document.querySelectorAll('.cat-card').length,
                                     roots: document.querySelectorAll('#catRoots .cat-item').length,
                                     inside: r.bottom <= innerHeight + 1 && r.left >= -1
                                             && r.right <= innerWidth + 1});
            """)
            step("分类界面能打开且盖住大厅",
                 cat_open.get("open") and cat_open.get("hall") and cat_open.get("cards") == 1
                 and cat_open.get("roots") == 3 and cat_open.get("inside"), cat_open)

            window.evaluate_js("document.getElementById('catNew').click()")
            time.sleep(0.5)
            window.evaluate_js("""
              document.getElementById('catName').value = 'E2E 分类';
              document.getElementById('catSave').click();
            """)
            time.sleep(1.6)
            made = probe(window, """
              return JSON.stringify({
                names: [...document.querySelectorAll('#catShelves .cat-item span:first-child')]
                         .map((s) => s.textContent.trim()),
                title: document.getElementById('catTitle').textContent,
                cards: document.querySelectorAll('.cat-card').length});
            """)
            step("新建分类后自动切到该分类",
                 "E2E 分类" in (made.get("names") or [])
                 and made.get("title") == "E2E 分类" and made.get("cards") == 0, made)

            window.evaluate_js("document.querySelector('#catRoots [data-scope=all]').click()")
            time.sleep(1.2)
            window.evaluate_js("document.querySelector('[data-cat=organize]').click()")
            time.sleep(0.7)
            window.evaluate_js("""
              for (const card of [...document.querySelectorAll('.cat-card')]) card.click();
            """)
            time.sleep(0.7)
            picked = probe(window, """
              return JSON.stringify({bar: !document.getElementById('catBar').hidden,
                                     marked: document.querySelectorAll('.cat-card.on').length});
            """)
            step("整理模式能勾选", picked.get("bar") and picked.get("marked") == 1, picked)

            window.evaluate_js("""
              const sel = document.getElementById('catTarget');
              sel.value = sel.options[1] ? sel.options[1].value : '';
              document.querySelector('[data-catbar=add]').click();
            """)
            time.sleep(1.8)
            shelf_id = (api._library.shelves() or [{}])[0].get("id", "")
            step("多选归类写进库",
                 bool(shelf_id) and shelf_id in (api._library.get(game_id).get("bookshelf_ids") or []),
                 f"shelf={shelf_id}")

            window.evaluate_js("document.querySelector('#catWall .cat-card').click()")
            time.sleep(0.7)
            window.evaluate_js("document.querySelector('[data-catbar=fav]').click()")
            time.sleep(1.6)
            favs = [bool(g.get("favorite")) for g in api._library.all()]
            step("整理模式能批量收藏", any(favs), str(favs))

            window.evaluate_js("document.querySelector('#catShelves .cat-item').click()")
            time.sleep(1.2)
            window.evaluate_js("document.querySelector('.vs-btn[data-view=home]').click()")
            time.sleep(1.5)
            scoped = probe(window, """
              return JSON.stringify({tiles: document.querySelectorAll('#hallRow .gi[data-id]').length,
                                     pill: document.getElementById('scopePill').hidden ? ""
                                       : document.getElementById('scopeLabel').textContent});
            """)
            step("主页按分类过滤 + 作用域胶囊",
                 scoped.get("tiles") == 1 and "E2E 分类" in (scoped.get("pill") or ""), scoped)

            window.evaluate_js("document.getElementById('scopePick').click()")
            time.sleep(1.3)
            scope_menu = probe(window, """
              const m = document.getElementById('scopeMenu');
              const r = m.getBoundingClientRect();
              const items = [...m.querySelectorAll('button[data-scope-type]')]
                .map((b) => b.textContent.trim());
              return JSON.stringify({open: !m.hidden, items: items,
                                     inside: r.bottom <= innerHeight + 1 && r.left >= -1
                                             && r.right <= innerWidth + 1});
            """)
            step("主页能直接选分类（作用域菜单）",
                 scope_menu.get("open")
                 and any("E2E 分类" in x for x in (scope_menu.get("items") or []))
                 and any("已收藏" in x for x in (scope_menu.get("items") or []))
                 and scope_menu.get("inside"), scope_menu)

            window.evaluate_js("""
              const btn = [...document.querySelectorAll('#scopeMenu button[data-scope-type]')]
                .find((b) => b.textContent.includes('已收藏'));
              btn.click();
            """)
            time.sleep(1.5)
            fav_scope = probe(window, """
              return JSON.stringify({label: document.getElementById('scopeLabel').textContent,
                                     tiles: document.querySelectorAll('#hallRow .gi[data-id]').length,
                                     menu: document.getElementById('scopeMenu').hidden});
            """)
            step("「已收藏」能当分类用",
                 fav_scope.get("menu") and "已收藏" in (fav_scope.get("label") or "")
                 and fav_scope.get("tiles") == 1, fav_scope)

            window.evaluate_js("document.getElementById('scopeClear').click()")
            time.sleep(1.3)
            cleared_scope = probe(window, """
              return JSON.stringify({tiles: document.querySelectorAll('#hallRow .gi[data-id]').length,
                                     cleared: document.getElementById('scopeClear').hidden,
                                     label: document.getElementById('scopeLabel').textContent});
            """)
            step("作用域胶囊能清除筛选",
                 cleared_scope.get("tiles") == 1 and cleared_scope.get("cleared")
                 and "全部" in (cleared_scope.get("label") or ""), cleared_scope)

            # 状态：从分类界面的封面打开详情面板再改
            window.evaluate_js("document.querySelector('.vs-btn[data-view=categories]').click()")
            time.sleep(1.5)
            window.evaluate_js("document.querySelector('#catShelves .cat-item').click()")
            time.sleep(1.3)
            window.evaluate_js("document.querySelector('.cat-card').click()")
            time.sleep(1.5)
            window.evaluate_js("""
              const sel = document.getElementById('detailStatus');
              sel.value = 'cleared';
              sel.dispatchEvent(new Event('change', {bubbles: true}));
            """)
            time.sleep(1.6)
            statuses = [g.get("status") for g in api._library.all()]
            step("详情面板能改游玩状态",
                 "cleared" in statuses and "playing" not in statuses, str(statuses))

            window.evaluate_js(
                "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
            time.sleep(1.2)
            window.evaluate_js("document.querySelector('.vs-btn[data-view=home]').click()")
            time.sleep(1.5)
            badge = probe(window, """
              return JSON.stringify({
                cleared: document.querySelectorAll('#hallRow .gi-badge.st-cleared').length,
                detail: document.getElementById('detailPanel').classList.contains('open')});
            """)
            step("封面显示状态徽标", badge.get("cleared") == 1 and not badge.get("detail"), badge)

            # 3.13 主题与配色
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.5)
            window.evaluate_js("""
              const sel = document.getElementById('setTheme');
              sel.value = 'light';
              sel.dispatchEvent(new Event('change', {bubbles: true}));
            """)
            time.sleep(1.6)
            light = probe(window, """
              const pane = document.querySelector('.set-panes');
              return JSON.stringify({theme: document.documentElement.dataset.theme,
                                     bg: getComputedStyle(pane).backgroundColor,
                                     chips: document.querySelectorAll('#setPalettes [data-palette]').length});
            """)
            step("浅色主题生效（面板转白、文字转深）",
                 light.get("theme") == "light" and "255, 255, 255" in (light.get("bg") or "")
                 and light.get("chips") == 4, light)

            window.evaluate_js("document.querySelector('#setPalettes [data-palette=lime]').click()")
            time.sleep(1.5)
            lime = probe(window, """
              return JSON.stringify({palette: document.documentElement.dataset.palette,
                                     accent: getComputedStyle(document.documentElement)
                                               .getPropertyValue('--accent').trim()});
            """)
            step("配色预设能切换",
                 lime.get("palette") == "lime"
                 and (lime.get("accent") or "").lower() == "#26c6a8", lime)

            window.evaluate_js("""
              const sel = document.getElementById('setTheme');
              sel.value = 'dark';
              sel.dispatchEvent(new Event('change', {bubbles: true}));
              document.querySelector('#setPalettes [data-palette=aurora]').click();
            """)
            time.sleep(1.5)
            back_dark = probe(window, """
              return JSON.stringify({theme: document.documentElement.dataset.theme,
                                     palette: document.documentElement.dataset.palette});
            """)
            step("能切回深色 + 默认配色",
                 back_dark.get("theme") == "dark" and back_dark.get("palette") == "aurora", back_dark)
            window.evaluate_js("document.getElementById('setBack').click()")
            time.sleep(1.3)

            # 3.14 重命名 / 删除分类
            window.evaluate_js("document.querySelector('.vs-btn[data-view=categories]').click()")
            time.sleep(1.5)
            window.evaluate_js("document.querySelector('#catShelves .cat-item').click()")
            time.sleep(1.2)
            window.evaluate_js("document.querySelector('[data-cat=rename]').click()")
            time.sleep(0.9)
            window.evaluate_js("""
              document.getElementById('modalInput').value = 'E2E 改名';
              document.getElementById('modalOk').click();
            """)
            time.sleep(1.5)
            renamed = probe(window, """
              return JSON.stringify({title: document.getElementById('catTitle').textContent,
                                     names: [...document.querySelectorAll('#catShelves .cat-item span:first-child')]
                                              .map((s) => s.textContent.trim())});
            """)
            step("能重命名分类",
                 renamed.get("title") == "E2E 改名"
                 and "E2E 改名" in (renamed.get("names") or []), renamed)

            window.evaluate_js("document.querySelector('[data-cat=delete]').click()")
            time.sleep(1.0)
            window.evaluate_js("document.getElementById('modalOk').click()")
            time.sleep(1.7)
            removed = probe(window, """
              return JSON.stringify({shelves: document.querySelectorAll('#catShelves .cat-item').length,
                                     title: document.getElementById('catTitle').textContent,
                                     cards: document.querySelectorAll('.cat-card').length});
            """)
            step("删除分类只解绑、退回全部",
                 removed.get("shelves") == 0 and removed.get("title") == "全部游戏"
                 and removed.get("cards") == 1, removed)
            window.evaluate_js("document.querySelector('.vs-btn[data-view=home]').click()")
            time.sleep(1.3)

            # 3.11 更多菜单 → 转区启动面板
            window.evaluate_js("document.getElementById('btnMore').click()")
            time.sleep(1.0)
            window.evaluate_js("document.querySelector('#moreMenu [data-act=locale]').click()")
            time.sleep(1.6)
            locale_panel = probe(window, """
              const p = document.getElementById('localePanel');
              const r = p.getBoundingClientRect();
              return JSON.stringify({
                open: p.classList.contains('open'),
                items: document.getElementById('locProfile').options.length,
                status: document.getElementById('locStatus').textContent,
                sub: document.getElementById('locSub').textContent,
                inside: r.bottom <= innerHeight + 1 && r.top >= -1});
            """)
            step("更多菜单能开转区面板",
                 locale_panel.get("open") and (locale_panel.get("items") or 0) >= 1
                 and bool(locale_panel.get("status")) and locale_panel.get("inside"),
                 locale_panel)

            window.evaluate_js("document.getElementById('locSwitch').click()")
            time.sleep(1.4)
            on_row = api._library.get(game_id)
            step("转区开关写进游戏记录", bool(on_row.get("locale_enabled")),
                 f"locale_enabled={on_row.get('locale_enabled')}")

            window.evaluate_js("document.getElementById('locSwitch').click()")
            time.sleep(1.4)
            off_row = api._library.get(game_id)
            step("转区开关能再关掉", not off_row.get("locale_enabled"),
                 f"locale_enabled={off_row.get('locale_enabled')}")
            window.evaluate_js(
                "document.getElementById('localePanel').classList.remove('open')")

            # 3.11.5 手动匹配：菜单入口 → 候选按匹配度列出，点了才应用
            before_match = api._library.get(game_id)
            window.evaluate_js("document.getElementById('btnMore').click()")
            time.sleep(0.8)
            menu_items = probe(window, """
              return JSON.stringify([...document.querySelectorAll('#moreMenu button')]
                .map((b) => b.textContent.trim()));
            """)
            window.evaluate_js("document.querySelector('#moreMenu [data-act=match]').click()")
            time.sleep(1.2)
            opened = probe(window, """
              const p = document.getElementById('matchPanel');
              return JSON.stringify({open: p.classList.contains('open'),
                                     query: document.getElementById('matchQuery').value});
            """)
            step("更多菜单里有「手动匹配…」并能打开候选面板",
                 any("手动匹配" in x for x in (menu_items or []))
                 and opened.get("open") and bool(opened.get("query")),
                 f"{menu_items} {opened}")

            # 换个关键词再搜：以前这一步会直接采纳最高分，现在应该只把候选列出来
            window.evaluate_js("""
              document.getElementById('matchQuery').value = 'Elden';
              document.getElementById('matchGo').click();
            """)
            deadline = time.time() + 90
            cand = {}
            while time.time() < deadline:
                time.sleep(1.5)
                cand = probe(window, """
                  return JSON.stringify({
                    rows: [...document.querySelectorAll('#matchList .match-item')].map((n) => ({
                      name: n.querySelector('.mi-name').textContent.trim(),
                      score: Number((n.querySelector('.match-score') || {}).textContent
                                     ? n.querySelector('.match-score').textContent.replace('%', '')
                                     : 0),
                      source: n.dataset.source})),
                    panel: document.getElementById('matchPanel').classList.contains('open'),
                    hint: document.getElementById('matchHint').textContent});
                """)
                if cand.get("rows"):
                    break
            rows = cand.get("rows") or []
            scores = [r["score"] for r in rows]
            after_match = api._library.get(game_id)
            step("手动搜索只列候选（按匹配度排序），不自动采纳",
                 len(rows) >= 1 and all(a >= b for a, b in zip(scores, scores[1:]))
                 and cand.get("panel")
                 and after_match.get("query_used") == before_match.get("query_used")
                 and after_match.get("match_source") == before_match.get("match_source"),
                 f"{len(rows)} 条 {scores[:4]} {[r['source'] for r in rows[:3]]} "
                 f"query_used={after_match.get('query_used')!r}")

            window.evaluate_js("document.querySelector('#matchList .match-item').click()")
            deadline = time.time() + 60
            applied = {}
            while time.time() < deadline:
                time.sleep(1.5)
                applied = probe(window, """
                  return JSON.stringify({panel: document.getElementById('matchPanel')
                                                   .classList.contains('open'),
                                         title: document.getElementById('gTitle').textContent,
                                         name: document.getElementById('hallName').textContent});
                """)
                if not applied.get("panel"):
                    break
            row_now = api._library.get(game_id)
            step("点候选才真正应用（面板关闭、来源标为手动）",
                 (not applied.get("panel")) and row_now.get("metadata_state") == "ok"
                 and row_now.get("match_source") == "manual",
                 f"{applied} match_source={row_now.get('match_source')} "
                 f"score={row_now.get('match_score')}")

            # 「重新搜索游戏信息」仍是自动流程：够准就直接采纳，不弹面板
            window.evaluate_js("document.getElementById('btnMore').click()")
            time.sleep(0.8)
            window.evaluate_js("document.querySelector('#moreMenu [data-act=research]').click()")
            deadline = time.time() + 60
            auto = {}
            while time.time() < deadline:
                time.sleep(1.5)
                auto = probe(window, """
                  return JSON.stringify({panel: document.getElementById('matchPanel')
                                                   .classList.contains('open'),
                                         toast: document.getElementById('toast').textContent});
                """)
                if auto.get("toast", "").startswith("已匹配"):
                    break
            auto_row = api._library.get(game_id)
            step("「重新搜索游戏信息」仍会自动采纳（不弹候选面板）",
                 (not auto.get("panel")) and auto_row.get("match_source") == "auto"
                 and auto_row.get("metadata_state") == "ok", auto)

            # 3.12 转区兜底：本机没装 LE 也要照常启动，只提示一句
            api.set_game_locale(game_id, True, "")
            api.set_launch_args(game_id, "-n 30 127.0.0.1")
            fallback_launch = api.launch(game_id)
            time.sleep(2.0)
            toast_state = probe(window, """
              return JSON.stringify({text: document.getElementById('toast').textContent,
                                     running: !document.getElementById('pillRunning').hidden});
            """)
            toast_text = toast_state.get("text") or ""
            step("开启转区后照常启动 + 有转区提示",
                 bool(fallback_launch.get("ok")) and api._pm.is_running(game_id)
                 and toast_state.get("running")
                 and ("Locale Emulator" in toast_text or "转区" in toast_text), toast_state)
            api.stop(game_id)
            api.set_game_locale(game_id, False, "")
            api.set_launch_args(game_id, "-n 30 127.0.0.1")
            time.sleep(1.5)

            # 3.6 双击封面直接启动（用 ping 冒充常驻进程）
            api.set_launch_args(game_id, "-n 30 127.0.0.1")
            window.evaluate_js(
                "document.querySelector('#hallRow .gi.focus').dispatchEvent("
                "new MouseEvent('dblclick',{bubbles:true}));")
            time.sleep(4)
            dbl = probe(window, """
              return JSON.stringify({page: !document.getElementById('view').hidden,
                                     running: !document.getElementById('pillRunning').hidden});
            """)
            step("双击封面直接启动", bool(dbl.get("running")) and api._pm.is_running(game_id), dbl)
            api.stop(game_id)
            time.sleep(2)

            # 4. 启动 / 结束（用 ping 冒充常驻进程）
            launched = api.launch(game_id)
            step("启动可执行文件", bool(launched.get("ok")), launched)
            time.sleep(3)
            state = probe(window, """
              const p = document.getElementById('pillRunning');
              return JSON.stringify({running: !p.hidden,
                                     label: (document.getElementById('playLabel')||{}).textContent});
            """)
            step("界面显示运行中", state.get("running") and state.get("label") == "结束游戏", state)
            step("进程确实在运行", api._pm.is_running(game_id))
            # 3.10b 游戏内翻译：设置页签 + 假钩子 + 流式译文 + 悬浮窗
            saved_llm = {
                "translate_base_url": api._library.settings.get("translate_base_url"),
                "translate_api_key": api._library.settings.get("translate_api_key"),
                "proxy_mode": api._library.settings.get("proxy_mode"),
            }
            api._library.set_setting("vntext_tractor_path", str(fake_cli))
            api._library.set_setting("translate_base_url", f"http://127.0.0.1:{llm_port}")
            api._library.set_setting("translate_api_key", "e2e-key")
            api._library.set_setting("proxy_mode", "direct")
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.5)
            window.evaluate_js(
                "document.querySelector('#setNav .set-tab[data-pane=vntext]').click()")
            time.sleep(1.8)
            vn_pane = probe(window, """
              const pane = document.querySelector('#settingsView .set-pane.on');
              return JSON.stringify({
                pane: pane && pane.dataset.pane,
                status: document.getElementById('vnStatus').textContent,
                ocr: document.getElementById('setVnOcr').textContent.slice(0, 40),
                path: document.getElementById('setVnPath').value});
            """)
            step("设置页有「游戏内翻译」页签且识别到 TextractorCLI",
                 vn_pane.get("pane") == "vntext"
                 and "TextractorCLI" in (vn_pane.get("status") or "")
                 and bool(vn_pane.get("ocr")), vn_pane)
            window.evaluate_js("document.getElementById('setBack').click()")
            time.sleep(1.3)

            # 游戏页的翻译面板（此时游戏正在运行，PID 已知）
            window.evaluate_js("document.getElementById('btnVntext').click()")
            time.sleep(1.5)
            started_vn = api.start_vntext(game_id)
            step("游戏内翻译能以钩子模式开启",
                 bool(started_vn.get("ok")) and started_vn.get("engine") == "hook",
                 f"{started_vn.get('engine')} / {started_vn.get('error')}")

            translated = ""
            deadline = time.time() + 25
            while time.time() < deadline and not translated:
                time.sleep(1.2)
                row = probe(window, """
                  const box = document.querySelector('#vnHistory .vn-row');
                  const state = document.getElementById('vnState').textContent;
                  return JSON.stringify({row: box ? box.textContent : "", state: state});
                """)
                if "微笑" in (row.get("row") or ""):
                    translated = row.get("row")
            step("假钩子的日文被翻成中文并进入面板", bool(translated),
                 (translated or "")[:60])

            vn_panel = probe(window, """
              // 只看 classList 会漏掉「面板 open 了但 CSS 没写规则、永远 opacity:0」
              // 这类问题，所以这里查计算样式
              const p = document.getElementById('vntextPanel');
              const cs = getComputedStyle(p);
              const rect = p.getBoundingClientRect();
              return JSON.stringify({
                open: p.classList.contains('open'),
                visible: cs.opacity !== '0' && cs.pointerEvents !== 'none' && rect.height > 10,
                threads: document.querySelectorAll('#vnThreads .vn-thread').length,
                state: document.getElementById('vnState').textContent});
            """)
            step("翻译面板可见且显示运行状态与线程",
                 vn_panel.get("open") and vn_panel.get("visible")
                 and vn_panel.get("threads", 0) >= 1
                 and "正在翻译" in (vn_panel.get("state") or ""), vn_panel)

            # 专用 hook 码（WillPlus 这类 Textractor 自带钩子搞不定的引擎）
            hook_saved = api.set_vntext_hook(game_id, "HQ-4@A22E:fake.exe")
            step("能存下这个游戏的专用 hook 码",
                 bool(hook_saved.get("ok"))
                 and hook_saved.get("vntext_hook") == "HQ-4@A22E:fake.exe"
                 and api._library.get(game_id).get("vntext_hook") == "HQ-4@A22E:fake.exe",
                 str(hook_saved.get("vntext_hook")))
            hook_bad = api.set_vntext_hook(game_id, "这不是 hook 码")
            step("乱填的 hook 码会被拒绝",
                 hook_bad.get("ok") is False and hook_bad.get("error") == "bad-code",
                 str(hook_bad.get("error")))
            hook_auto = api.set_vntext_hook(game_id, "")
            step("清空后改回自动",
                 bool(hook_auto.get("ok")) and not (hook_auto.get("vntext_hook") or ""),
                 str(hook_auto.get("vntext_hook")))

            overlay_text = ""
            if len(webview.windows) >= 2:
                try:
                    overlay_text = webview.windows[-1].evaluate_js(
                        "document.getElementById('trans').textContent")
                except Exception as exc:
                    overlay_text = f"err {exc}"
            step("悬浮窗已创建并显示译文",
                 len(webview.windows) >= 2 and "微笑" in str(overlay_text),
                 f"{len(webview.windows)} 个窗口 / {str(overlay_text)[:40]}")

            stopped_vn = api.stop_vntext()
            time.sleep(1.2)
            step("能停止翻译且悬浮窗收起",
                 not stopped_vn.get("running")
                 and not stopped_vn.get("overlay_open"), str(stopped_vn.get("overlay_open")))

            for key, value in saved_llm.items():
                api._library.set_setting(key, value)
            window.evaluate_js("document.getElementById('vnClose').click()")
            time.sleep(1.0)


            stopped = api.stop(game_id)
            step("结束进程", bool(stopped.get("ok")), stopped)
            time.sleep(2)
            step("进程已退出", not api._pm.is_running(game_id))

            # 5. 数据持久化
            reloaded = api._library.get(game_id)
            step("元数据已持久化", bool(reloaded.get("appid")) and bool(reloaded.get("description")),
                 f"appid={reloaded.get('appid')}", skipped=net_down)

            # 6. 无边框窗口：拖拽 / 缩放 / 最大化（全部按物理像素）
            before = app_main.winapi.get_rect(window)
            api.drag_start()
            api.drag_move(120, 60)
            api.drag_end()
            time.sleep(1.2)
            after = app_main.winapi.get_rect(window)
            step("拖拽移动窗口", (after[0] - before[0], after[1] - before[1]) == (120, 60),
                 f"{before[:2]} -> {after[:2]}")

            api.resize_apply(after[0], after[1], after[2] - 120, after[3] - 80, "se")
            time.sleep(1.2)
            size1 = app_main.winapi.get_rect(window)
            step("拖拽缩放窗口", (size1[2], size1[3]) == (after[2] - 120, after[3] - 80),
                 f"{after[2:]} -> {size1[2:]}")

            api.resize_apply(size1[0], size1[1], 100, 100, "se")
            time.sleep(1.2)
            size2 = app_main.winapi.get_rect(window)
            scale = app_main.winapi.dpi_scale(window)
            step("最小尺寸被钳制", size2[2] >= int(1040 * scale) and size2[3] >= int(660 * scale),
                 f"{size2[2:]} (scale={scale:.2f})")

            maximized = api.window_cmd("toggle_maximize")
            time.sleep(1.5)
            step("最大化窗口", bool(maximized.get("maximized")) and app_main.winapi.is_maximized(window),
                 maximized)
            api.window_cmd("toggle_maximize")
            time.sleep(1.5)
            step("还原窗口", not app_main.winapi.is_maximized(window))

            # 7. 最小窗口（1040×660）下设置页与转区面板仍然完整
            window.evaluate_js("document.getElementById('btnSettings').click()")
            time.sleep(1.6)
            narrow = probe(window, """
              const v = document.getElementById('settingsView');
              const pane = v.querySelector('.set-pane.on');
              const nav = document.getElementById('setNav');
              const r = v.getBoundingClientRect();
              return JSON.stringify({
                open: !v.hidden, vw: innerWidth, vh: innerHeight,
                navRight: Math.round(nav.getBoundingClientRect().right),
                paneRight: pane ? Math.round(pane.getBoundingClientRect().right) : 0,
                inside: r.bottom <= innerHeight + 1 && r.right <= innerWidth + 1
                        && r.top >= -1 && r.left >= -1});
            """)
            step("最小窗口下设置页不溢出",
                 narrow.get("open") and narrow.get("inside")
                 and narrow.get("paneRight", 1e9) <= narrow.get("vw", 0),
                 narrow)

            window.evaluate_js("document.getElementById('setBack').click()")
            time.sleep(1.2)
            narrow_back = probe(window, """
              return JSON.stringify({settings: !document.getElementById('settingsView').hidden,
                                     hall: !document.getElementById('hall').hidden,
                                     view: !document.getElementById('view').hidden,
                                     title: (document.getElementById('gTitle') || {}).textContent});
            """)
            step("返回按钮能退出设置页（回到进来前的页面）",
                 (not narrow_back.get("settings"))
                 and (narrow_back.get("hall") or narrow_back.get("view")), narrow_back)
        except Exception as exc:  # pragma: no cover
            import traceback

            step("异常", False, traceback.format_exc()[-400:])
        finally:
            OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            passed = sum(1 for r in results if r["ok"])
            skipped = sum(1 for r in results if r.get("skipped"))
            print(f"\n{passed}/{len(results)} passed, {skipped} skipped -> {OUT}")
            # 悬浮窗也是 pywebview 窗口：不关掉主循环不会退出，脚本会一直挂着
            for extra in list(webview.windows)[1:]:
                try:
                    extra.destroy()
                except Exception:
                    pass
            try:
                window.destroy()
            except Exception:
                pass

    window.events.loaded += lambda: threading.Thread(target=run, daemon=True).start()
    webview.start(gui="edgechromium", private_mode=False, http_port=app_main.free_port(),
                  storage_path=str(TEST_DATA / "webview"))
    return 0 if all(r["ok"] or r.get("skipped") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
