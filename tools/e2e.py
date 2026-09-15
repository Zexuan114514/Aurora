"""端到端自检：空状态 -> 导入 -> 自动联网搜索 -> 切换背景 -> 启动/结束进程。"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
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
    exe = EXE_DIR / "eldenring.exe"
    if not exe.exists():
        shutil.copy2(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "ping.exe", exe)

    api = Api()
    window = app_main.build_window(api)
    api._window = window

    def run() -> None:
        time.sleep(6)
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

            # 3.5 大厅导航（封面横滑）
            hall = probe(window, """
              return JSON.stringify({
                tiles: document.querySelectorAll('#hallRow .gi').length,
                add: !!document.querySelector('#hallRow .gi-add'),
                focus: document.getElementById('hallName').textContent,
                cx: (() => { const t = document.querySelector('#hallRow .gi.focus');
                             const r = t.getBoundingClientRect();
                             return Math.round(r.x + r.width / 2); })(),
                vw: innerWidth,
              });
            """)
            step("大厅出现封面块", hall.get("tiles") == 2 and hall.get("add"), hall)
            step("焦点封面居中", abs((hall.get("cx") or 0) - (hall.get("vw") or 0) / 2) <= 2,
                 f"cx={hall.get('cx')} vw={hall.get('vw')}")

            key = ("const k='%s'; document.dispatchEvent("
                   "new KeyboardEvent('keydown',{key:k,bubbles:true})); return 1;")
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

            window.evaluate_js(
                "document.getElementById('app').dispatchEvent("
                "new WheelEvent('wheel',{deltaY:120,bubbles:true,cancelable:true}));")
            time.sleep(1.0)
            wheeled = probe(window, "return JSON.stringify({focus: document.getElementById('hallName').textContent});")
            step("滚轮切换封面", wheeled.get("focus") != back_hall.get("focus"), wheeled)
            window.evaluate_js("(() => { %s })()" % (key % "ArrowLeft"))
            time.sleep(1.0)

            window.evaluate_js("document.querySelector('#hallRow .gi.focus').click()")
            time.sleep(1.2)
            entered = probe(window, """
              return JSON.stringify({hall: document.getElementById('hall').hidden,
                                     view: !document.getElementById('view').hidden,
                                     title: document.getElementById('gTitle').textContent,
                                     back: !document.getElementById('btnBack').hidden});
            """)
            step("单击封面进入游戏页",
                 entered.get("hall") and entered.get("view") and entered.get("back")
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

            # 3.8 设置页：整页 + 六个页签
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
                 and len(settings.get("tabs") or []) == 6
                 and settings.get("tabs") == settings.get("panes")
                 and settings.get("inside"), settings)

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
