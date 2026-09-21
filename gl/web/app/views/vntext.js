/* Aurora 前端 · 游戏内翻译面板（P4.3-p）
 *
 * 这一块是 `app.js` 里剩下的最大一坨：面板状态渲染、设置页里的翻译/OCR 一栏、
 * 术语表、OCR 框选，以及自研钩子查找器的整套交互。
 *
 * 与其它视图同规矩：只 import core（api / dom / panels / store）；提示用
 * `createVntextView(ctx)` 注入的 `toast`；事件绑定由 `bind()` 一次性挂上，
 * 主模块的推送事件通过 `renderPanel` / `onHookSearch` / `refresh` / `renderGlossary` 转进来。
 */
import { call } from "../core/api.js";
import { $, el, esc } from "../core/dom.js";
import { closeAll, closePanel, openPanel } from "../core/panels.js";
import { state, ADD_KEY } from "../core/store.js";

const VN_ENGINE_LABEL = { hook: "Textractor 钩子", ocr: "屏幕 OCR", "": "未运行" };

const VN_ERROR_LABEL = {
  "no-textractor": "没找到 TextractorCLI，请在设置里指定，或改用 OCR 模式",
  "no-language": "系统缺少日语 OCR 组件，装好后再试",
  "no-winrt": "OCR 组件不可用（缺少 winrt 运行库）",
  "no-window": "没找到游戏窗口，先启动游戏再试",
  "no-pid": "还没定位到游戏进程，等游戏跑起来再开启",
  "capture-failed": "抓不到游戏画面，试试让游戏窗口化运行",
  "textractor-failed": "启动 TextractorCLI 失败",
  "hook-closed": "TextractorCLI 已退出",
  "wrong-bitness": "TextractorCLI 位数和目标游戏不一致，注入不了",
};

export function createVntextView(ctx) {
  let vnEmptySince = 0;          // 「一直没抓到文本」的起始时间（提醒用）
  let vnFindTimer = null;        // 查找器会话期间的状态轮询
  const vnFindHooks = {};        // {render, poll}，bind() 时装上，refresh() 复用
  let frameRect = null;          // OCR 框选：当前拖出来的框

  const vnErrorText = (status) => {
    const error = (status && status.error) || "";
    return VN_ERROR_LABEL[error] || error;
  };

  function renderVntextPanel(status) {
    if (!status) return;
    const running = !!status.running;
    $("vnToggle").firstElementChild.textContent = running ? "停止翻译" : "开启翻译";
    $("vnPause").firstElementChild.textContent = status.paused ? "继续" : "暂停";
    const parts = [running ? `正在翻译（${VN_ENGINE_LABEL[status.engine || ""] || status.engine}）`
                           : "未开启"];
    if (running && status.pid) parts.push(`PID ${status.pid}`);
    parts.push(`已译 ${status.lines || 0} 句`);
    if (running && !status.llm_ready) parts.push("没配 LLM Key：正在用免费接口，质量与速度较差");
    if (status.engine_name && status.engine_name !== "unknown") {
      parts.push(`引擎：${status.engine_name}`);
    }
    if (status.merged) parts.push(`已合并 ${status.merged} 份重复文本`);
    if (status.gated) parts.push(`已按线程过滤 ${status.gated} 条杂讯`);
    if (status.hook_hint) parts.push(status.hook_hint);
    // 「没抓到文本」提醒（不自动执行，只提示；用户点了才开查找器）
    if (running && status.engine === "hook" && !(status.lines || 0)
        && !((status.threads || []).length)) {
      if (!vnEmptySince) vnEmptySince = Date.now();
      if (Date.now() - vnEmptySince > 15000) {
        parts.push("没抓到文本？点下面的「找不到文本？开始侦测」让 Aurora 自己找钩子");
      }
    } else {
      vnEmptySince = 0;
    }
    if (running && status.engine === "hook" && status.game_locale === false) {
      parts.push("这个游戏没开转区：日文原版很容易出乱码，建议用「⋯ → 转区启动…」开启后再翻译");
    }
    const hk = status.hotkeys || {};
    if (running && hk.registered && hk.registered.length) {
      parts.push("Ctrl+Alt+T 切换穿透");
    } else if (running) {
      parts.push("全局热键没注册成功（可能被别的软件占用），请点下面的「切换穿透」");
    }
    const error = vnErrorText(status);
    let detail = error;
    if (status.error === "wrong-bitness") {
      detail = `这个游戏是 ${status.target_bits || "?"} 位，当前的 TextractorCLI 是 ${
        status.cli_bits || "?"} 位；请在 设置 → 游戏内翻译 里换成 ${
        status.target_bits === 32 ? "x86" : "x64"} 版`;
    }
    el.vnState.textContent = parts.join(" · ") + (detail ? ` · ${detail}` : "");

    const locked = status.locked || "";
    el.vnThreads.innerHTML = (status.threads || []).map((row) => `
      <button class="vn-thread${row.key === locked ? " on" : ""}" data-vn-thread="${esc(row.key)}"
              title="${esc(row.sample || "")}">
        <span>${esc(row.name || row.key)}</span><small>${row.count}</small>
      </button>`).join("");

    const region = status.region || {};
    $("vnRegion").textContent = `x${Math.round((region.x || 0) * 100)}% y${
      Math.round((region.y || 0) * 100)}% · ${Math.round((region.w || 1) * 100)}%×${
      Math.round((region.h || 0.34) * 100)}%`;

    // 专用 hook 码（WillPlus 这类 Textractor 自带钩子搞不定的引擎）：
    // 输入框里显示实际生效的那条；下面是「已存 / 自动带出」的说明
    const savedHook = status.game_hook || "";
    const autoHook = status.hook_auto || "";
    const liveHook = status.hook_code || "";
    const hookBox = $("vnHook");
    if (document.activeElement !== hookBox) {
      hookBox.value = liveHook || savedHook || autoHook || "";
    }
    $("vnHookNote").textContent = savedHook
      ? `本游戏专用 hook 码：${savedHook}（清空输入框再点「存为专用」= 改用自动）`
      : (autoHook
         ? `已按实测记录自动带出：${autoHook}`
         : "Textractor 自带钩子搞不定的引擎（如 WillPlus/AdvHD）：Aurora 会用"
           + "「内存补全」把缺字版配成完整台词，一般不用手动填。想更稳可以在上面填专用 hook 码："
           + "HQ-4@<模块内偏移>:<exe文件名>（Q=UTF-16，S=字节串，V=UTF-8），点「存为专用」下次自动带上。");

    const history = status.history || [];
    el.vnHistory.innerHTML = history.slice(-6).reverse().map((row) => `
      <div class="vn-row"><i>${esc(row.text)}</i>${esc(row.translation)}${row.fallback_from
        ? `<b class="vn-fb">插件未响应，已兜底 ${esc(row.provider)}</b>` : ""}</div>`).join("")
      || '<div class="vn-row"><i>还没有译文</i>开启翻译后，游戏里的日文会实时出现在这里和悬浮窗上。</div>';
  }

  function renderVntextSettings(status) {
    const tractor = status.tractor || {};
    $("setVnPath").value = tractor.path || tractor.saved || "";
    $("setVnContext").value = status.context_lines ?? 4;
    $("setVnContextVal").textContent = (status.context_lines ?? 4) + " 句";
    $("setVnAuto").checked = !!status.auto_start;
    const overlay = status.overlay || {};
    const font = overlay.font || 20;
    const opacity = Math.round((overlay.opacity ?? 0.9) * 100);
    $("setVnFont").value = font;
    $("setVnFontVal").textContent = font + "px";
    $("setVnOpacity").value = opacity;
    $("setVnOpacityVal").textContent = opacity + "%";
    const ocrInfo = status.ocr || {};
    $("setVnOcr").textContent = ocrInfo.lang_ready
      ? "日语 OCR 组件已就绪，可以只用 OCR 模式。OCR 读的是屏幕上的对话框，"
        + "所以游戏窗口要露在最前面（被别的窗口盖住时抓不到）。"
      : `系统还没装「日语 OCR」组件（当前可用：${(ocrInfo.languages || []).join(" / ") || "无"}）。`
        + "点「安装日语 OCR 组件…」按提示添加日语并勾选光学字符识别。";
    $("vnStatus").textContent = tractor.found
      ? `TextractorCLI：${tractor.path}`
      : "没有检测到 TextractorCLI。装好 Textractor 后点「重新检测」，或手动指定；只用 OCR 也可以。";
    const builds = status.builds || [];
    $("setVnBuilds").innerHTML = builds.map((row) => {
      const label = row.bits === 32 ? "x86" : (row.bits === 64 ? "x64" : "未知位数");
      const bits = row.bits ? `${row.bits} 位` : "位数未知";
      const on = (tractor.path || "").toLowerCase() === row.path.toLowerCase();
      return `<button class="vn-build${on ? " on" : ""}" data-vn-build="${esc(row.path)}"
                      title="${esc(row.path)}">
        <b>${label}</b><span>${esc(row.path)}</span><i>${bits}</i>
      </button>`;
    }).join("") || "";
  }

  async function refresh() {
    let status = null;
    try {
      status = await call("get_vntext_status");
    } catch (_) { /* 离线时保留原样 */ }
    if (status) {
      renderVntextPanel(status);
      renderVntextSettings(status);
    }
    if (vnFindHooks.poll) vnFindHooks.poll();     // 面板重开时恢复查找器状态
    return status;
  }

  async function renderGlossary() {
    let data = null;
    try {
      data = await call("list_glossary");
    } catch (_) { return; }
    const gameId = state.focus && state.focus !== ADD_KEY ? state.focus : "";
    const global = (data && data.global) || {};
    const perGame = ((data && data.games) || {})[gameId] || {};
    const rows = [
      ...Object.entries(global).map(([src, dst]) => ({ src, dst, scope: "" })),
      ...Object.entries(perGame).map(([src, dst]) => ({ src, dst, scope: gameId })),
    ];
    $("glossaryList").innerHTML = rows.map((row) => `
      <span class="glossary-chip">${esc(row.src)}<i>→</i>${esc(row.dst)}${
        row.scope ? '<i title="仅这个游戏">·本作</i>' : ""}
        <button data-glossary-del="${esc(row.src)}" data-scope="${esc(row.scope)}">✕</button>
      </span>`).join("") || '<span class="hint">还没有术语，遇到人名/专有名词可以加进来。</span>';
  }

  async function setGlossary(src, dst, gameId = "") {
    const res = await call("set_glossary_entry", src, dst, gameId);
    if (!res || !res.ok) { ctx.toast("术语表更新失败"); return; }
    await renderGlossary();
    ctx.toast(dst ? "已加入术语表" : "已删除术语");
  }

  function openVntextPanel() {
    closeAll();
    openPanel(el.vntextPanel);
    refresh();
  }

  /* OCR 区域框选：先截一张游戏窗口图，再在上面拖框 */
  async function openFraming() {
    const gameId = state.focus;
    if (!gameId || gameId === ADD_KEY) return;
    const res = await call("capture_game_frame", gameId);
    if (!res || !res.ok) {
      ctx.toast("截图失败：" + (vnErrorText({ error: (res && res.error) || "" }) || "未知原因"), 4200);
      return;
    }
    el.frameImg.src = res.url;
    el.frameSel.hidden = true;
    frameRect = null;
    el.frameBox.hidden = false;
    el.frameBox.dataset.game = gameId;
  }

  function bindFraming() {
    const stage = $("frameStage");
    let start = null;
    stage.addEventListener("mousedown", (e) => {
      const rect = el.frameImg.getBoundingClientRect();
      if (e.clientX < rect.left || e.clientX > rect.right
          || e.clientY < rect.top || e.clientY > rect.bottom) return;
      start = { x: e.clientX - rect.left, y: e.clientY - rect.top, rect: rect };
      el.frameSel.hidden = false;
    });
    document.addEventListener("mousemove", (e) => {
      if (!start) return;
      const rect = start.rect;
      const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const y = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
      const left = Math.min(start.x, x);
      const top = Math.min(start.y, y);
      const width = Math.abs(x - start.x);
      const height = Math.abs(y - start.y);
      frameRect = { left, top, width, height, base: rect };
      el.frameSel.style.left = (rect.left + left) + "px";
      el.frameSel.style.top = (rect.top + top) + "px";
      el.frameSel.style.width = width + "px";
      el.frameSel.style.height = height + "px";
    });
    document.addEventListener("mouseup", () => { start = null; });
    $("frameCancel").onclick = () => { el.frameBox.hidden = true; frameRect = null; };
    $("frameOk").onclick = async () => {
      const gameId = el.frameBox.dataset.game;
      const rect = el.frameImg.getBoundingClientRect();
      if (!frameRect || frameRect.width < 8 || frameRect.height < 8) {
        ctx.toast("先拖一个框"); return;
      }
      const region = {
        x: frameRect.left / rect.width,
        y: frameRect.top / rect.height,
        w: frameRect.width / rect.width,
        h: frameRect.height / rect.height,
      };
      await call("set_vntext_region", gameId, region);
      el.frameBox.hidden = true;
      frameRect = null;
      ctx.toast("已记住这个游戏的 OCR 区域");
      refresh();
    };
  }

  /* 主模块推送：面板状态 / 查找器状态 / 新译文 */
  function renderPanel(status) {
    renderVntextPanel(status);
  }

  function onHookSearch(payload) {
    if (vnFindHooks.render) vnFindHooks.render(payload);
    const phase = (payload || {}).phase;
    if (vnFindTimer && (phase === "idle" || phase === "done" || phase === "error")) {
      clearInterval(vnFindTimer);
      vnFindTimer = null;
    }
  }

  function bind() {
    $("btnVntext").onclick = openVntextPanel;
    $("vnClose").onclick = () => closePanel(el.vntextPanel);
    $("vnToggle").onclick = async () => {
      const status = await call("get_vntext_status");
      if (status && status.running) {
        await call("stop_vntext");
        ctx.toast("已停止翻译");
      } else {
        const res = await call("start_vntext", state.focus);
        ctx.toast(res && res.ok ? "翻译已开启，悬浮窗会显示译文"
                                : "开启失败：" + (vnErrorText(res || {}) || "未知原因"), 5200);
      }
      refresh();
    };
    $("vnPush").onclick = async () => {
      const res = await call("toggle_overlay");
      ctx.toast(res && res.visible ? "悬浮窗已显示" : "悬浮窗已隐藏");
    };
    $("vnRetry").onclick = async () => {
      const last = el.vnHistory.querySelector("i");
      const res = await call("translate_line_now", last ? last.textContent : "");
      ctx.toast(res && res.ok ? "正在重译…" : "还没有可重译的台词");
    };
    $("vnThrough").onclick = async () => {
      const status = await call("get_vntext_status");
      const on = !(status && status.overlay && status.overlay.click_through === false);
      const res = await call("set_overlay_click_through", on);
      ctx.toast(on ? "悬浮窗已设为鼠标穿透"
                   : "悬浮窗已可点击：拖标题栏移动，拖右下角或任意边缘缩放");
      refresh();
    };
    $("vnPause").onclick = async () => {
      const status = await call("get_vntext_status");
      const res = await call("set_vntext_paused", !(status && status.paused));
      ctx.toast(res && res.paused ? "已暂停翻译" : "已继续翻译");
      refresh();
    };
    $("vnHookSend").onclick = async () => {
      const code = $("vnHook").value.trim();
      if (!code) { ctx.toast("先粘贴 hook 码"); return; }
      const res = await call("send_hook_code", code);
      ctx.toast(res && res.ok ? "已发送 hook 码" : "发送失败（当前不是钩子模式）");
      refresh();
    };
    $("vnHookSave").onclick = async () => {
      const code = $("vnHook").value.trim();
      const res = await call("set_vntext_hook", state.focus, code);
      if (!res || res.ok === false) {
        ctx.toast((res && res.hint) || "hook 码格式不对，应该像 HQ-4@A22E:AdvHD_crack.exe", 5200);
      } else {
        ctx.toast(code ? "已存为这个游戏的专用 hook 码（下次开翻译自动带上）"
                       : "已清除专用 hook 码，改回自动");
      }
      refresh();
    };
    // 自研钩子查找器：找不到文本时手动触发（会临时附加调试器，期间游戏可能卡一下）
    const PHASE_LABEL = { idle: "未开始", starting: "准备中", ocr: "识别台词",
                          seeding: "按特征码找绘制函数",
                          scanning: "定位文本", collecting: "等待游戏访问",
                          verifying: "验证候选", done: "成功", error: "失败" };
    const renderFind = (hs) => {
      if (!hs) return;
      const phase = hs.phase || "idle";
      $("vnFindNote").textContent =
        `[${PHASE_LABEL[phase] || phase}] ${hs.message || ""}`
        + (hs.target ? ` · 目标：${hs.target.slice(0, 24)}` : "")
        + (hs.code ? ` · 已存：${hs.code}` : "");
      const cands = hs.candidates || [];
      $("vnFindCands").innerHTML = cands.map((row) => `
        <button class="vn-thread${row.verified ? " on" : ""}" data-vn-find="${esc(row.code)}"
                title="点一下 = 存为该游戏的专用码">
          <span>${esc(row.code)}</span><small>${row.verified ? "已验证" : (row.count || 0)}</small>
        </button>`).join("");
      if (phase === "idle" || phase === "done" || phase === "error") {
        if (vnFindTimer) { clearInterval(vnFindTimer); vnFindTimer = null; }
      }
    };
    const pollFind = async () => {
      const hs = await call("get_hook_search_status");
      renderFind(hs);
    };
    vnFindHooks.render = renderFind;
    vnFindHooks.poll = pollFind;
    $("vnFind").onclick = async () => {
      const text = $("vnFindText").value.trim();
      const res = await call("start_hook_search", state.focus, text);
      if (!res || res.ok === false) {
        ctx.toast((res && res.message) || "现在没法开始查找", 5200);
        renderFind(res);
        return;
      }
      renderFind(res);
      if (!vnFindTimer) vnFindTimer = setInterval(pollFind, 1500);
      ctx.toast("开始侦测：请在游戏里点一下推进台词（或点「翻一页」）", 5200);
    };
    $("vnFindStop").onclick = async () => {
      await call("stop_hook_search");
      ctx.toast("已中止查找");
      pollFind();
    };
    $("vnAdvance").onclick = async () => {
      const res = await call("advance_game", state.focus);
      ctx.toast(res && res.ok ? `已翻页（${res.how}）` : "没送出去：先把游戏窗口点到前台");
    };
    $("vnFindCands").addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-vn-find]");
      if (!btn) return;
      const res = await call("set_vntext_hook", state.focus, btn.dataset.vnFind);
      ctx.toast(res && res.ok !== false ? "已存为这个游戏的专用 hook 码" : "保存失败");
      refresh();
    });
    el.vnThreads.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-vn-thread]");
      if (!btn) return;
      const key = btn.dataset.vnThread;
      const current = btn.classList.contains("on");
      await call("lock_vntext_thread", current ? "" : key);
      ctx.toast(current ? "已取消锁定线程" : "已锁定这个线程");
      refresh();
    });
    $("vnFraming").onclick = openFraming;
    bindFraming();

    $("setVnEngine").onchange = async (e) => {
      state.settings.vntext_engine = e.target.value;
      await call("set_vntext_option", "vntext_engine", e.target.value);
      ctx.toast("已切换翻译引擎");
      refresh();
    };
    $("setVnPick").onclick = async () => {
      const res = await call("pick_textractor");
      if (!res || res.cancelled) return;
      if (!res.ok) { ctx.toast("这个路径不可用"); return; }
      ctx.toast("已指定 TextractorCLI");
      refresh();
    };
    $("setVnBuilds").addEventListener("click", async (e) => {
      const chip = e.target.closest("[data-vn-build]");
      if (!chip) return;
      const res = await call("set_vntext_option", "vntext_tractor_path", chip.dataset.vnBuild);
      if (!res || !res.ok) { ctx.toast("这个路径不可用"); return; }
      ctx.toast("已切换 TextractorCLI");
      refresh();
    });
    $("setVnDownload").onclick = () => call("open_textractor_page");
    $("setVnRefresh").onclick = () => { refresh(); ctx.toast("已重新检测"); };
    $("setVnLang").onclick = () => call("open_language_settings");
    $("setVnContext").oninput = (e) => { $("setVnContextVal").textContent = e.target.value + " 句"; };
    $("setVnContext").onchange = (e) =>
      call("set_vntext_option", "vntext_context_lines", Number(e.target.value));
    $("setVnAuto").onchange = async (e) => {
      await call("set_vntext_option", "vntext_auto_start", e.target.checked);
      ctx.toast(e.target.checked ? "启动游戏时会自动开始翻译" : "已关闭自动翻译");
    };
    $("setVnFont").oninput = (e) => { $("setVnFontVal").textContent = e.target.value + "px"; };
    $("setVnFont").onchange = (e) => call("set_overlay_style", { font: Number(e.target.value) });
    $("setVnOpacity").oninput = (e) => {
      $("setVnOpacityVal").textContent = e.target.value + "%";
    };
    $("setVnOpacity").onchange = (e) =>
      call("set_overlay_style", { opacity: Number(e.target.value) / 100 });
    $("glossaryAdd").onclick = () => {
      const src = $("glossarySrc").value.trim();
      const dst = $("glossaryDst").value.trim();
      if (!src || !dst) { ctx.toast("日文和中文都要填"); return; }
      setGlossary(src, dst, $("glossaryGame").checked ? state.focus : "");
      $("glossarySrc").value = "";
      $("glossaryDst").value = "";
    };
    $("glossaryList").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-glossary-del]");
      if (btn) setGlossary(btn.dataset.glossaryDel, "", btn.dataset.scope || "");
    });
  }

  return { bind, refresh, renderGlossary, renderPanel, onHookSearch };
}
