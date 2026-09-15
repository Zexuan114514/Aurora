/* ============================================================
   Aurora 游戏启动器 · 前端逻辑
   ============================================================ */
(() => {
  "use strict";

  // 最小尺寸由后端按显示器缩放比例钳制（见 gl/api.py: resize_apply）
  /* 记录找不到的元素：HTML 与 JS 对不上时报出来，而不是整页静默死掉 */
  const missingIds = new Set();
  const $ = (id) => {
    const node = document.getElementById(id);
    if (!node) missingIds.add(id);
    return node;
  };
  const el = {
    boot: $("boot"), empty: $("empty"), view: $("view"),
    hall: $("hall"), hallRow: $("hallRow"), hallViewport: $("hallViewport"),
    hallName: $("hallName"), hallSub: $("hallSub"), hallCount: $("hallCount"),
    sortMenu: $("sortMenu"), btnBack: $("btnBack"),
    search: $("searchInput"),
    searchClear: $("searchClear"),
    title: $("gTitle"), logo: $("gLogo"), chips: $("gChips"), desc: $("gDesc"),
    play: $("btnPlay"), playLabel: $("playLabel"),
    fetching: $("fetching"), fetchTitle: $("fetchTitle"), fetchSub: $("fetchSub"),
    pillSource: $("pillSource"), pillRunning: $("pillRunning"),
    bgPanel: $("bgPanel"), bgGrid: $("bgGrid"), bgCount: $("bgCount"),
    detailPanel: $("detailPanel"), detailBody: $("detailBody"),
    dTitle: $("dTitle"), dSub: $("dSub"),
    matchPanel: $("matchPanel"), matchList: $("matchList"), matchQuery: $("matchQuery"),
    matchLinks: $("matchLinks"),
    sourcePanel: $("sourcePanel"), sourceList: $("sourceList"), sourceForm: $("sourceForm"),
    coverPanel: $("coverPanel"), coverGrid: $("coverGrid"),
    steamPanel: $("steamPanel"), steamList: $("steamList"),
    steamImport: $("steamImport"), steamSub: $("steamSub"),
    steamPickHint: $("steamPickHint"),
    getPanel: $("getPanel"), getSiteForm: $("getSiteForm"),
    getQuery: $("getQuery"), getDir: $("getDir"),
    getDirHint: $("getDirHint"), getWatch: $("getWatch"), getExtract: $("getExtract"),
    getSites: $("getSites"), addMenu: $("addMenu"),
    localePanel: $("localePanel"),
    translateHint: $("translateHint"),
    showOriginal: $("btnShowOriginal"),
    moreMenu: $("moreMenu"),
    settingsView: $("settingsView"), setNav: $("setNav"),
    netStatus: $("netStatus"), netResults: $("netResults"),
    leStatus: $("leStatus"), leProfiles: $("leProfiles"),
    toast: $("toast"),
    dropHint: $("dropHint"),
    modal: $("modal"), modalTitle: $("modalTitle"), modalBody: $("modalBody"),
    modalInput: $("modalInput"), modalOk: $("modalOk"), modalCancel: $("modalCancel"),
  };

  const state = {
    games: [],
    focus: null,          // 焦点游戏的 id（大厅与游戏页共用），导入块为 "__add__"
    page: "hall",         // hall | game
    settingsOpen: false,
    settingsTab: "look",
    settings: {},
    sources: [],
    filter: "",
    sort: "default",
    version: "",
    dpr: window.devicePixelRatio || 1,
    busy: {},
    iconFor: null,
    steam: [],
    picked: new Set(),
    batch: null,
    sites: [],
  };

  let pywebviewReady = false;
  let drag = null;
  let resize = null;
  let toastTimer = null;
  let bgCurrent = null;
  let bgSide = "a";
  let bgTimer = null;            // 焦点切换后的背景防抖
  let swipe = null;              // 横向滑动

  /* ---------------------------------------------------------- 工具 */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const cssUrl = (u) => `url("${String(u).replace(/"/g, '\\"')}")`;

  function toast(msg, ms = 2600) {
    el.toast.textContent = msg;
    el.toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.toast.classList.remove("show"), ms);
  }

  function modal({ title, body, input, value, okText, presets }) {
    return new Promise((resolve) => {
      el.modalTitle.textContent = title || "提示";
      el.modalBody.textContent = body || "";
      el.modalInput.hidden = !input;
      el.modalInput.value = value || "";
      el.modalOk.textContent = okText || "确定";
      const presetBox = $("modalPresets");
      presetBox.innerHTML = (presets || []).map((p) =>
        `<button type="button" class="preset-chip">${esc(p)}</button>`).join("");
      presetBox.hidden = !(presets && presets.length);
      presetBox.onclick = (e) => {
        const chip = e.target.closest(".preset-chip");
        if (!chip) return;
        el.modalInput.value = (el.modalInput.value.trim() + " " + chip.textContent).trim();
        el.modalInput.focus();
      };
      el.modal.hidden = false;
      if (input) setTimeout(() => { el.modalInput.focus(); el.modalInput.select(); }, 60);

      const done = (result) => {
        el.modal.hidden = true;
        el.modalOk.removeEventListener("click", onOk);
        el.modalCancel.removeEventListener("click", onCancel);
        el.modalInput.removeEventListener("keydown", onKey);
        resolve(result);
      };
      const onOk = () => done(input ? el.modalInput.value.trim() : true);
      const onCancel = () => done(null);
      const onKey = (e) => {
        if (e.key === "Enter") { e.preventDefault(); onOk(); }
        if (e.key === "Escape") { e.preventDefault(); onCancel(); }
      };
      el.modalOk.addEventListener("click", onOk);
      el.modalCancel.addEventListener("click", onCancel);
      el.modalInput.addEventListener("keydown", onKey);
    });
  }

  const api = () => (window.pywebview && window.pywebview.api) || null;
  const call = async (name, ...args) => {
    const a = api();
    if (!a || typeof a[name] !== "function") throw new Error("bridge not ready");
    return a[name](...args);
  };

  const hours = (sec) => {
    if (sec >= 3600) return (sec / 3600).toFixed(sec >= 36000 ? 0 : 1) + " 小时";
    const minutes = Math.round(sec / 60);
    return minutes < 1 ? "不到 1 分钟" : minutes + " 分钟";
  };

  /* 运行中的实时计时：00:35 / 1:02:03 */
  const clock = (sec) => {
    const total = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  };

  const sessionSeconds = (game) =>
    game.session_started_at ? Math.floor(Date.now() / 1000) - game.session_started_at : 0;

  /* 会话历史里的时间戳（秒）-> 2026-09-15 21:30 */
  const stamp = (ts) => {
    const d = new Date((Number(ts) || 0) * 1000);
    if (!ts) return "—";
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
      + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  function hashHue(text) {
    let h = 0;
    for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) % 360;
    return h;
  }

  function fallbackBackground(game) {
    const hue = hashHue(game.name || game.id || "aurora");
    return `linear-gradient(150deg,
      hsl(${hue} 46% 26%) 0%,
      hsl(${(hue + 42) % 360} 40% 15%) 48%,
      hsl(${(hue + 96) % 360} 34% 9%) 100%)`;
  }

  /* 空库时的默认极光背景 */
  const DEFAULT_BACKGROUND = [
    "radial-gradient(120% 92% at 12% 4%, rgba(38,66,150,.85) 0%, rgba(38,66,150,0) 56%)",
    "radial-gradient(108% 82% at 90% 8%, rgba(104,52,140,.78) 0%, rgba(104,52,140,0) 58%)",
    "radial-gradient(130% 100% at 52% 112%, rgba(14,86,110,.72) 0%, rgba(14,86,110,0) 62%)",
    "linear-gradient(162deg, #0b1024 0%, #080a15 52%, #05050a 100%)",
  ].join(", ");

  /* ---------------------------------------------------------- 背景 */
  const bgLayer = () => (bgSide === "a" ? $("bg-a") : $("bg-b"));

  function bgViewOf(game) {
    return {
      scale: Math.max(1, Number(game && game.bg_scale) || 1),
      x: 0,
      y: 0,
    };
  }

  function bgTransform(view) {
    return view.scale === 1 && !view.x && !view.y
      ? "" : `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})`;
  }

  function applyBgView(view, layer) {
    (layer || bgLayer()).style.transform = bgTransform(view);
  }

  function applyBackground(source, view, animate = true) {
    const a = $("bg-a"), b = $("bg-b");
    const cur = bgSide === "a" ? a : b;
    const nxt = bgSide === "a" ? b : a;
    if (bgCurrent === source) { applyBgView(view, cur); return; }
    bgCurrent = source;

    if (!source) {
      cur.classList.remove("on");
      nxt.classList.remove("on");
      return;
    }

    const isGradient = source.startsWith("linear-gradient") || source.startsWith("radial-gradient");
    const ken = !!state.settings.ken_burns && !isGradient;

    const swap = () => {
      const inner = nxt.querySelector(".bg-img");
      inner.style.backgroundImage = isGradient ? source : cssUrl(source);
      inner.classList.toggle("ken", ken);
      applyBgView(view, nxt);
      void nxt.offsetWidth;
      nxt.classList.add("on");
      if (animate) cur.classList.remove("on");
      else { cur.classList.remove("on"); nxt.style.transition = "none"; void nxt.offsetWidth; nxt.style.transition = ""; }
      bgSide = bgSide === "a" ? "b" : "a";
    };

    if (isGradient) { swap(); return; }
    const probe = new Image();
    probe.onload = swap;
    probe.onerror = () => { bgCurrent = null; toast("背景图加载失败"); };
    probe.src = source;
  }

  /* ---------------------------------------------------------- 渲染 */
  function visibleGames() {
    let list = state.games.slice();
    const q = state.filter.trim().toLowerCase();
    if (q) {
      list = list.filter((g) =>
        [g.name, g.steam_name, g.name_cn, g.name_original, g.exe_name, g.dir,
         (g.developers || []).join(" "), (g.publishers || []).join(" "),
         (g.genres || []).join(" "), (g.categories || []).join(" ")]
          .join(" ")
          .toLowerCase().includes(q));
    }
    if (state.sort === "favorite") {
      list.sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0));
    } else if (state.sort === "name") list.sort((a, b) => a.name.localeCompare(b.name, "zh"));
    else if (state.sort === "recent") list.sort((a, b) => (b.last_played || 0) - (a.last_played || 0));
    else if (state.sort === "playtime") list.sort((a, b) => (b.play_time || 0) - (a.play_time || 0));
    return list;
  }

  /* 图片回退链：img[data-srcs] 里按顺序放备用地址，加载失败自动换下一个 */
  function imgHtml(cls, sources, attrs = "") {
    const list = (Array.isArray(sources) ? sources : [sources]).filter(Boolean);
    if (!list.length) return "";
    const rest = list.slice(1);
    return `<img class="${cls}" src="${esc(list[0])}"` +
      (rest.length ? ` data-srcs="${esc(JSON.stringify(rest))}"` : "") +
      ` alt="" loading="lazy" decoding="async" ${attrs}>`;
  }

  function coverSources(game) {
    // 大厅是大封面：优先用 2 倍图（Steam 的 library_600x900 其实只有 300×450）
    const list = [];
    const push = (url) => {
      if (url && !list.includes(url)) list.push(url);
    };
    if (game.custom_cover) push(game.custom_cover);
    const sources = (game.cover_sources || []).slice();
    sources.filter((u) => /600x900_2x/.test(u)).forEach(push);
    sources.filter((u) => !/600x900_2x/.test(u)).forEach(push);
    push(game.cover);
    push(game.header_image);
    push(game.custom_icon);      // 图标是方图，只当最后的兜底
    return list;
  }

  /* 封面候选：手动封面 > 封面链 > 全部图片 */
  function coverCandidates(game) {
    const out = [];
    const seen = new Set();
    const push = (url, label) => {
      if (!url || seen.has(url)) return;
      seen.add(url);
      out.push({ url, label: label || "" });
    };
    push(game.custom_cover, "当前封面");
    push(game.cover, "默认封面");
    (game.cover_sources || []).forEach((u) => push(u, "封面候选"));
    (game.images || []).forEach((img) => push(img.url, img.label || ""));
    return out.slice(0, 24);
  }

  /* ---------------------------------------------------------- 大厅 */
  const ADD_KEY = "__add__";

  const currentGame = () =>
    state.games.find((x) => x.id === state.focus) || null;

  /* 大厅里的一项：游戏封面，或末尾的「导入游戏」色块 */
  function tileHtml(game) {
    if (game === ADD_KEY) {
      return `<button class="gi gi-add${state.focus === ADD_KEY ? " focus" : ""}" data-add="1">
        <svg viewBox="0 0 24 24" class="ic"><path d="M12 5v14M5 12h14"/></svg>
        <span>导入游戏</span>
        <span class="gi-ring"></span>
      </button>`;
    }
    const letter = esc((game.name || "?").trim().charAt(0).toUpperCase());
    const busy = game.metadata_state === "searching" || state.busy[game.id];
    const badges = [];
    if (game.running) badges.push('<span class="gi-badge run">●</span>');
    if (game.favorite) badges.push('<span class="gi-badge fav">★</span>');
    if (game.locale_enabled) badges.push('<span class="gi-badge loc">JP</span>');
    if (game.missing) badges.push('<span class="gi-badge warn">!</span>');
    else if (game.metadata_state === "notfound") badges.push('<span class="gi-badge warn">?</span>');
    return `<button class="gi${game.id === state.focus ? " focus" : ""}${
      busy ? " searching" : ""}" data-id="${esc(game.id)}" title="${esc(game.name)}">
      <span class="gi-cover">${imgHtml("", coverSources(game))}<b>${letter}</b></span>
      <span class="veil"></span>
      ${badges.length ? `<span class="gi-badges">${badges.join("")}</span>` : ""}
      <span class="gi-ring"></span>
    </button>`;
  }

  /* 把焦点那张封面滚到窗口正中 */
  let firstPaint = true;
  function updateRow(instant = false) {
    const row = el.hallRow;
    const index = hallKeys().indexOf(state.focus);
    if (index < 0) return;
    const tile = row.children[index];
    if (!tile) return;
    const noAnim = instant || firstPaint;   // 首帧与窗口缩放直接就位
    if (noAnim) {
      firstPaint = false;
      row.style.transition = "none";
    }
    const vp = el.hallViewport.getBoundingClientRect();
    const center = tile.offsetLeft + tile.offsetWidth / 2;
    const x = Math.round(vp.width / 2 - center);
    row.style.transform = `translate3d(${x}px, 0, 0)`;
    if (noAnim) requestAnimationFrame(() => { row.style.transition = ""; });
  }

  const hallKeys = () => {
    const ids = visibleGames().map((g) => g.id);
    ids.push(ADD_KEY);
    return ids;
  };

  function renderHall() {
    const list = visibleGames();
    const hasGames = state.games.length > 0;
    el.empty.hidden = hasGames;
    el.hall.hidden = !hasGames;
    if (state.page === "game") el.hall.hidden = true;
    if (!hasGames) return;
    const keys = hallKeys();
    el.hallRow.innerHTML = keys.map((key) =>
      tileHtml(key === ADD_KEY ? ADD_KEY : state.games.find((g) => g.id === key))).join("");
    if (!keys.includes(state.focus)) {
      state.focus = keys[0];
    }
    syncFocusUi();
    // 等新 DOM 完成布局再算位移，避免首帧跳动
    requestAnimationFrame(updateRow);
  }

  /* 焦点变化后：更新高亮、底部信息、背景与窗口图标 */
  function syncFocusUi() {
    for (const node of el.hallRow.children) {
      const key = node.dataset.add ? ADD_KEY : node.dataset.id;
      node.classList.toggle("focus", key === state.focus);
    }
    const game = currentGame();
    const filtered = state.filter.trim();
    el.hallCount.textContent = filtered
      ? `匹配 ${visibleGames().length} / 共 ${state.games.length} 个游戏`
      : `共 ${state.games.length} 个游戏`;
    if (!game) {
      el.hallName.textContent = "导入游戏";
      el.hallSub.textContent = "选择一个 .exe / .bat，或把游戏文件夹拖进窗口";
      return;
    }
    const bits = [game.developers[0], (game.release_date || "").match(/\d{4}/)?.[0]];
    if (game.genres[0]) bits.push(game.genres[0]);
    if (game.play_time > 0) bits.push(`已玩 ${hours(game.play_time)}`);
    if (game.running) bits.push("运行中");
    el.hallName.textContent = game.name;
    el.hallSub.textContent = bits.filter(Boolean).join(" · ") || game.exe_name;
  }

  /* 焦点变化 → 背景延迟淡入 + 预取邻居 */
  function scheduleBackground() {
    const game = currentGame();
    if (!game) return;
    clearTimeout(bgTimer);
    bgTimer = setTimeout(() => {
      applyBackground(game.background || fallbackBackground(game), bgViewOf(game));
      // 预取相邻封面/背景，滑动时更跟手
      const keys = hallKeys();
      const index = keys.indexOf(state.focus);
      [index - 1, index + 1].forEach((i) => {
        const near = state.games.find((g) => g.id === keys[i]);
        if (near && near.background) { const img = new Image(); img.src = near.background; }
      });
    }, 140);
  }

  function setFocus(id, opts = {}) {
    if (!id || id === state.focus) {
      if (opts.scroll !== false) updateRow();
      return;
    }
    state.focus = id;
    const game = currentGame();
    // 窗口/任务栏图标跟着当前游戏走
    const wantIcon = game && game.custom_icon ? game.id : "";
    if (state.iconFor !== wantIcon) {
      state.iconFor = wantIcon;
      call("apply_window_icon", wantIcon).catch(() => {});
    }
    renderGameContent();
    syncFocusUi();
    if (opts.scroll !== false) updateRow();
    scheduleBackground();
    if (opts.persist !== false) {
      try { localStorage.setItem("aurora.focus", state.focus); } catch (_) {}
    }
  }

  function moveFocus(delta) {
    const keys = hallKeys();
    if (!keys.length) return;
    const index = keys.indexOf(state.focus);
    const next = Math.min(keys.length - 1, Math.max(0, (index < 0 ? 0 : index) + delta));
    if (next !== index) setFocus(keys[next]);
  }

  function jumpFocus(edge) {
    const keys = hallKeys();
    if (!keys.length) return;
    setFocus(edge === "end" ? keys[keys.length - 1] : keys[0]);
  }

  /* 大厅 ↔ 游戏页 */
  function openGame(id) {
    if (id) state.focus = id;
    if (!currentGame()) return;
    state.page = "game";
    renderGameContent();
    el.hall.hidden = true;
    el.view.hidden = false;
    document.body.classList.add("page-game");
    closeAll();
    scheduleBackground();
  }

  function closeGame() {
    state.page = "hall";
    el.view.hidden = true;
    el.hall.hidden = state.games.length === 0;
    document.body.classList.remove("page-game");
    renderHall();
  }

  function chip(text, accent) {
    return `<span class="chip${accent ? " accent" : ""}">${esc(text)}</span>`;
  }

  /* 简介文本：显示原文还是译文由 show_original 决定 */
  function descText(g) {
    const orig = (g.description_original || "").trim();
    if (state.settings.show_original && orig) return orig;
    return g.description || g.description_translated || g.about?.slice(0, 220) || "";
  }

  function updateShowOriginalBtn(g) {
    const btn = el.showOriginal;
    if (!btn) return;
    const hasBoth = !!(g && g.description_translated
      && (g.description_original || "").trim()
      && g.description_translated !== g.description_original);
    btn.hidden = !hasBoth;
    if (hasBoth) btn.textContent = state.settings.show_original ? "显示译文" : "显示原文";
  }

  /* 详情正文：有译文时跟着卡片显示译文，否则用长简介（原文） */
  function detailBody(g) {
    const shown = descText(g);
    if (g.description_translated) return shown || g.about || "";
    return g.about || shown || "";
  }

  /* 游戏页（以及大厅底部的）文字内容 */
  function renderGameContent() {
    const g = currentGame();
    if (!g) {
      el.fetching.hidden = true;
      el.title.textContent = "—";
      el.desc.textContent = "";
      el.chips.innerHTML = "";
      el.logo.hidden = true;
      el.logo.removeAttribute("src");
      return;
    }
    syncBgZoomUi(g);

    // 标题 / LOGO
    if (g.logo) {
      el.logo.src = g.logo;
      el.logo.hidden = false;
      el.logo.onerror = () => { el.logo.hidden = true; };
    } else {
      el.logo.hidden = true;
      el.logo.removeAttribute("src");
    }
    el.title.textContent = g.name;

    // 信息条
    const bits = [];
    if (g.developers[0]) bits.push(chip(g.developers[0]));
    const year = (g.release_date || "").match(/\d{4}/)?.[0];
    if (year) bits.push(chip(year));
    g.genres.slice(0, 2).forEach((x) => bits.push(chip(x)));
    if (g.metacritic) bits.push(chip(`Metacritic ${g.metacritic}`, true));
    if (g.locale_enabled) bits.push(chip("转区启动"));
    if (g.play_time > 0) bits.push(chip(`已玩 ${hours(g.play_time)}`));
    if (g.running) {
      bits.push(`<span class="chip accent" id="chipLive">运行中 · <b>${clock(sessionSeconds(g))}</b></span>`);
    }
    if (g.missing) bits.push(chip("可执行文件不存在", true));
    if (!g.running && g.metadata_state === "notfound" && /网络/.test(g.metadata_note || "")) {
      bits.push(chip("上次搜索没连上网络", true));
    }
    el.chips.innerHTML = bits.join("");

    // 简介（原文/译文由 show_original 决定）
    el.desc.textContent = descText(g)
      || (g.metadata_state === "ok" ? "这款游戏没有提供简介。" : "正在获取游戏简介…");
    updateShowOriginalBtn(g);

    // 运行状态
    el.pillRunning.hidden = !g.running;
    el.play.classList.toggle("running", !!g.running);
    el.playLabel.textContent = g.running ? "结束游戏" : "开始游戏";
    if (g.running) startLiveTicker();

    // 数据来源
    if (g.data_source || g.match_source) {
      el.pillSource.hidden = false;
      const parts = [];
      if (g.data_source) parts.push(sourceName(g.data_source));
      parts.push(g.match_source === "manual" ? "手动匹配" : "自动匹配");
      if (g.match_score != null) parts.push(`${Math.round(g.match_score * 100)}%`);
      el.pillSource.textContent = parts.join(" · ");
    } else {
      el.pillSource.hidden = true;
    }

    // 加载遮罩
    const busy = g.metadata_state === "searching" || state.busy[g.id];
    el.fetching.hidden = !busy;
    if (busy) {
      el.fetchTitle.textContent = "正在搜索游戏信息…";
      el.fetchSub.textContent = (g.queries || []).slice(0, 2).join(" / ") || g.exe_name;
    }
  }

  function render() {
    renderHall();
    renderGameContent();
    if (state.settingsOpen) {
      el.hall.hidden = true;
      el.view.hidden = true;
      el.empty.hidden = true;
      el.settingsView.hidden = false;
    }
  }

  /* ---------------------------------------------------------- 设置页 */
  function setSettingsTab(name) {
    state.settingsTab = name || "look";
    for (const tab of el.setNav.querySelectorAll(".set-tab")) {
      tab.classList.toggle("on", tab.dataset.pane === state.settingsTab);
    }
    for (const pane of el.settingsView.querySelectorAll(".set-pane")) {
      pane.classList.toggle("on", pane.dataset.pane === state.settingsTab);
    }
  }

  async function openSettings(tab) {
    state.settingsOpen = true;
    closeAll();
    render();
    setSettingsTab(tab || state.settingsTab);
    await refreshSettingsPanes();
  }

  function closeSettings() {
    state.settingsOpen = false;
    el.settingsView.hidden = true;
    render();
  }

  async function refreshSettingsPanes() {
    $("aboutVersion").textContent = state.version || "—";
    try {
      const info = await call("bootstrap");
      $("aboutDataDir").textContent = info.data_dir || "—";
      state.settings = info.settings || state.settings;
      state.version = info.version || state.version;
      $("aboutVersion").textContent = state.version || "—";
      applySettingsToUi();
    } catch (_) { /* 离线也要能开设置 */ }
    refreshNetworkPane();
    refreshLocalePane();
  }

  /* ---------------------------------------------------------- 背景面板 */
  function renderBgPanel() {
    const g = currentGame();
    if (!g) return;
    const images = g.images || [];
    el.bgCount.textContent = images.length ? `共 ${images.length} 张可选` : "暂无可选图片";
    if (!images.length) {
      el.bgGrid.innerHTML = `<div class="list-empty" style="grid-column:1/-1">
        ${g.metadata_state === "ok" ? "该游戏没有可用图片，试试从本地选择。"
                                    : "还没有获取到图片，先完成游戏信息搜索。"}</div>`;
      return;
    }
    el.bgGrid.innerHTML = images.map((img) => {
      const sources = [img.thumb, img.url].filter(Boolean);
      return `
      <button class="bg-item${img.url === g.background ? " active" : ""}"
              data-url="${esc(img.url)}" data-kind="${esc(img.kind)}"
              title="${esc(img.label || "")}">
        <span class="bg-thumb">${imgHtml("", sources)}<i>无法预览</i></span>
        <span class="bg-label">${esc(img.label || "")}</span>
      </button>`;
    }).join("");
    syncBgZoomUi(g);
  }

  /* 背景缩放 UI 与状态同步 */
  function syncBgZoomUi(game) {
    const g = game || currentGame();
    if (!g) return;
    const scale = Math.round((Number(g.bg_scale) || 1) * 100);
    $("bgZoom").value = Math.min(300, Math.max(100, scale));
    $("bgZoomVal").textContent = scale + "%";
  }

  /* 修改当前游戏的背景缩放（缩放只由滑杆控制） */
  let bgViewTimer = null;

  function updateBgView(next, persist = true) {
    const g = currentGame();
    if (!g) return;
    const view = { scale: Math.max(1, Math.min(3, Number(next.scale) || 1)), x: 0, y: 0 };
    g.bg_scale = view.scale;
    g.bg_x = 0;
    g.bg_y = 0;
    applyBgView(view);
    syncBgZoomUi(g);
    if (!persist) return;
    clearTimeout(bgViewTimer);
    bgViewTimer = setTimeout(() => {
      call("set_background_view", g.id, g.bg_scale, g.bg_x, g.bg_y).catch(() => {});
    }, 350);
  }

  /* ---------------------------------------------------------- 详情面板 */
  function renderDetail() {
    const g = currentGame();
    if (!g) return;
    el.dTitle.textContent = g.name;
    el.dSub.textContent = g.name_original && g.name_original !== g.name
      ? g.name_original : g.exe_name;

    const srcName = sourceName(g.data_source);
    const rows = [
      ["可执行文件", `<span title="${esc(g.exe)}">${esc(g.exe_name)}</span>`],
      ["所在目录", `<span title="${esc(g.dir)}">${esc(g.dir)}</span>`],
      ["运行状态", g.running
        ? `运行中 · PID ${g.play_pid || "-"} · 本次 ${clock(sessionSeconds(g))}` : ""],
      ["资料源", srcName],
      ["原名", g.name_original],
      ["中文名", g.name_cn],
      ["开发商", g.developers.join("、")],
      ["发行商", g.publishers.join("、")],
      ["发行日期", g.release_date],
      ["类型", g.genres.join("、")],
      ["特性", g.categories.slice(0, 5).join("、")],
      ["评分", g.rating],
      ["启动次数", g.play_count ? `${g.play_count} 次` : ""],
      ["累计游玩", g.play_time ? hours(g.play_time) : ""],
      ["转区启动", g.locale_enabled ? "已开启" : ""],
      ["匹配关键词", g.query_used],
      ["启动参数", g.launch_args],
      ["来源页面", g.source_url ? `<a data-url="${esc(g.source_url)}">打开</a>` : ""],
    ].filter(([, v]) => v);

    let shots = (g.images || []).filter((img) => img.kind === "screenshot");
    if (!shots.length) shots = (g.images || []).slice(0, 8);
    const shotWall = shots.length ? `
       <h4>截图 <span class="hint">点一张可设为背景</span></h4>
       <div class="shot-grid">${shots.slice(0, 12).map((img) => `
         <button class="shot" data-shot="${esc(img.url)}" data-kind="${esc(img.kind || "screenshot")}"
                 title="${esc(img.label || "")}">
           ${imgHtml("", [img.thumb, img.url])}<i>${esc(img.label || "")}</i>
         </button>`).join("")}</div>` : "";

    const sessions = (g.sessions || []).slice(-5).reverse();
    const history = (g.play_count || g.play_time || sessions.length) ? `
       <h4>游玩记录 <span class="hint">启动 ${g.play_count || 0} 次${
         g.play_time ? ` · 累计 ${hours(g.play_time)}` : ""}</span></h4>
       ${sessions.length
         ? `<div class="session-list">${sessions.map((s) => `
             <div class="session-row"><span>${esc(stamp(s.started_at))}</span><b>${clock(s.seconds)}</b></div>`)
             .join("")}</div>`
         : '<p class="hint">还没有结束过的会话，游戏跑完一次就会记在这里。</p>'}` : "";

    el.detailBody.innerHTML =
      `<p>${esc(detailBody(g) || "暂无简介。")}</p>
       <h4>详细信息</h4>
       <dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>
       ${history}
       ${shotWall}`;
  }

  /* ---------------------------------------------------------- 封面面板 */
  function renderCoverPanel() {
    const g = currentGame();
    if (!g) return;
    const list = coverCandidates(g);
    if (!list.length) {
      el.coverGrid.innerHTML = `<div class="list-empty" style="grid-column:1/-1">
        还没有可用图片，可以先用「从本地选择图片」。</div>`;
      return;
    }
    el.coverGrid.innerHTML = list.map((row) => `
      <button class="bg-item${row.url === g.custom_cover ? " active" : ""}"
              data-cover="${esc(row.url)}" title="${esc(row.label)}">
        <span class="bg-thumb">${imgHtml("", [row.url])}<i>无法预览</i></span>
        <span class="bg-label">${esc(row.label)}</span>
      </button>`).join("");
  }

  function openCoverPanel() {
    closeAll();
    renderCoverPanel();
    openPanel(el.coverPanel);
  }

  /* ---------------------------------------------------------- Steam 扫描 */
  function renderSteamList() {
    const rows = state.steam || [];
    if (!rows.length) {
      el.steamList.innerHTML = `<div class="list-empty">没有找到可导入的游戏</div>`;
      return;
    }
    el.steamList.innerHTML = rows.map((row) => `
      <label class="steam-row${row.already ? " off" : ""}">
        <input type="checkbox" class="switch sm" data-exe="${esc(row.exe)}"
               ${state.picked.has(row.exe) ? "checked" : ""} ${row.already ? "disabled" : ""}>
        <div class="steam-body">
          <div class="steam-name">${esc(row.name)}
            ${row.already ? '<span class="src-badge">已在库中</span>' : ""}</div>
          <div class="steam-meta">${esc(row.exe_name)} · ${esc(row.dir)}</div>
        </div>
        <span class="src-badge">${esc(String(row.appid))}</span>
      </label>`).join("");
    updateSteamHint();
  }

  function updateSteamHint() {
    const picked = state.picked.size;
    const active = (state.steam || []).filter((r) => !r.already).length;
    el.steamPickHint.textContent = picked ? `已选 ${picked} 个` : `可导入 ${active} 个`;
    el.steamImport.disabled = !picked;
    el.steamImport.textContent = picked ? `导入选中的 ${picked} 个游戏` : "导入选中的游戏";
  }

  async function openSteamPanel() {
    closeAll();
    state.steam = [];
    state.picked = new Set();
    openPanel(el.steamPanel);
    el.steamSub.textContent = "正在读取 Steam 清单…";
    el.steamList.innerHTML = `<div class="list-empty">正在扫描 Steam 库，第一次可能要十几秒…</div>`;
    el.steamImport.disabled = true;
    try {
      const res = await call("scan_steam");
      if (!res || !res.ok) {
        el.steamSub.textContent = (res && res.error === "no-steam")
          ? "没有在注册表里找到 Steam" : "扫描失败：" + ((res && res.error) || "未知错误");
        el.steamList.innerHTML = `<div class="list-empty">没找到可导入的 Steam 游戏</div>`;
        return;
      }
      state.steam = res.games || [];
      state.steam.forEach((row) => { if (!row.already) state.picked.add(row.exe); });
      el.steamSub.textContent =
        `找到 ${state.steam.length} 个游戏 · ${(res.libraries || []).length} 个库目录`;
      renderSteamList();
    } catch (e) {
      el.steamSub.textContent = "扫描失败：" + e.message;
      el.steamList.innerHTML = `<div class="list-empty">扫描失败</div>`;
    }
  }

  async function importSteam() {
    const items = (state.steam || [])
      .filter((row) => state.picked.has(row.exe))
      .map((row) => ({ exe: row.exe, appid: row.appid, name: row.name }));
    if (!items.length) return;
    state.batch = { kind: "steam", done: 0, total: items.length };
    el.steamImport.disabled = true;
    el.steamImport.textContent = `导入中 0/${items.length}`;
    const res = await call("import_steam_games", items);
    if (!res || !res.ok) {
      state.batch = null;
      updateSteamHint();
      toast("导入失败：" + ((res && res.error) || "未知错误"));
    }
  }

  /* ---------------------------------------------------------- 批量重新抓取 */

  /* ---------------------------------------------------------- 获取游戏 */
  function renderSites() {
    const sites = state.sites || [];
    if (!sites.length) {
      el.getSites.innerHTML = '<span class="get-hint">还没有资源站，点右边「＋ 添加站点」加一个</span>';
      return;
    }
    el.getSites.innerHTML = sites.map((row) => `
      <span class="site-chip">
        <button class="link-chip" data-site="${esc(row.id)}"
                title="${esc(row.url)}">${esc(row.name)}</button>
        <button class="site-del" data-del="${esc(row.id)}" title="删除这个站点">×</button>
      </span>`).join("");
  }

  async function refreshSites() {
    try {
      const res = await call("list_sites");
      state.sites = (res && res.sites) || [];
    } catch (_) {
      state.sites = state.sites || [];
    }
    renderSites();
  }

  async function openSite(siteId) {
    const res = await call("open_site", siteId, el.getQuery.value.trim());
    if (!res || !res.ok) toast("打不开这个站点：" + ((res && res.error) || ""));
  }

  async function addSite() {
    const name = $("getSiteName").value.trim();
    const url = $("getSiteUrl").value.trim();
    if (!name || !url) { toast("名称和地址都要填"); return; }
    const res = await call("add_site", name, url);
    if (!res || !res.ok) {
      toast(res && res.error === "bad-url" ? "地址要以 http:// 或 https:// 开头" : "添加失败");
      return;
    }
    state.sites = res.sites || [];
    renderSites();
    el.getSiteForm.hidden = true;
    toast(`已添加资源站：${name}`);
  }

  async function refreshDownloadSettings() {
    try {
      const s = await call("get_download_settings");
      if (!s || !s.ok) return;
      el.getDir.textContent = s.dir || "—";
      el.getWatch.checked = !!s.watch;
      el.getExtract.checked = !!s.extract;
      el.getDirHint.textContent = s.extractor
        ? `· 解压工具：${s.extractor} 已就绪`
        : "· 没找到解压工具（.zip 内置；.rar/.7z 需装 7-Zip 或 WinRAR）";
    } catch (_) { /* 面板还没准备好就忽略 */ }
  }

  async function openGetPanel() {
    closeAll();
    openPanel(el.getPanel);
    await refreshSites();
    await refreshDownloadSettings();
  }

  /* ---------------------------------------------------------- 批量重新抓取 */
  async function startRefreshAll() {
    if (state.batch) { toast("已经有一个批量任务在跑"); return; }
    // 先占位，避免后端第一批进度事件比这里更早到达而被丢掉
    state.batch = { kind: "refresh", done: 0, total: 0 };
    const res = await call("refresh_all_metadata");
    if (!res || !res.ok) {
      state.batch = null;
      toast(res && res.error === "empty" ? "库里还没有游戏" : "启动失败，请稍后再试");
      return;
    }
    state.batch.total = res.total;
    $("refreshHint").textContent = `0/${res.total}`;
    toast(`开始重新抓取 ${res.total} 个游戏的资料`);
  }

  /* ---------------------------------------------------------- 批量翻译简介 */
  async function startTranslateAll() {
    if (state.batch) { toast("已经有一个批量任务在跑"); return; }
    state.batch = { kind: "translate", done: 0, total: 0 };
    const res = await call("translate_all_descriptions");
    if (!res || !res.ok) {
      state.batch = null;
      toast(res && res.error === "empty" ? "库里还没有游戏" : "启动失败，请稍后再试");
      return;
    }
    state.batch.total = res.total;
    $("translateHint").textContent = `0/${res.total}`;
    toast(`开始翻译 ${res.total} 个游戏的简介`);
  }

  /* ---------------------------------------------------------- 候选匹配 */
  function sourceName(id) {
    const row = (state.sources || []).find((s) => s.id === id);
    if (row) return row.name;
    return id ? id : "";
  }

  function renderMatches(candidates, query) {
    el.matchQuery.value = query || "";
    renderMatchLinks(query);
    if (!candidates || !candidates.length) {
      el.matchList.innerHTML =
        `<div class="list-empty">没有找到候选，换个关键词试试，或检查设置里的资料源。</div>`;
      return;
    }
    el.matchList.innerHTML = candidates.map((c) => `
      <button class="match-item" data-source="${esc(c.source)}"
              data-source-id="${esc(c.source_id)}" data-name="${esc(c.name)}">
        ${c.thumb ? `<img src="${esc(c.thumb)}" alt="" loading="lazy">` : `<img alt="">`}
        <div>
          <div class="mi-name">${esc(c.name)}</div>
          <div class="mi-sub">
            <span class="src-badge">${esc(sourceName(c.source))}</span>
            <span>${esc(c.source_id)}</span>
          </div>
        </div>
        <span class="match-score">${Math.round((c.score || 0) * 100)}%</span>
      </button>`).join("");
  }

  /* 只跳转搜索的源（如 TouchGal），点一下用浏览器打开 */
  function renderMatchLinks(query) {
    const links = (state.sources || []).filter((s) => s.kind === "link" && s.enabled);
    const text = (query || el.matchQuery.value || "").trim();
    if (!links.length || !text) {
      el.matchLinks.innerHTML = "";
      return;
    }
    el.matchLinks.innerHTML = links.map((s) => `
      <button class="link-chip" data-link-source="${esc(s.id)}">
        <svg viewBox="0 0 24 24" class="ic" style="width:13px;height:13px">
          <path d="M14 5h5v5M19 5l-8 8M9 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-3"/>
        </svg>
        在 ${esc(s.name)} 搜索
      </button>`).join("");
  }

  /* ---------------------------------------------------------- 资料源管理 */
  function renderSources() {
    const list = state.sources || [];
    if (!list.length) {
      el.sourceList.innerHTML = `<div class="list-empty">还没有启用任何资料源</div>`;
      return;
    }
    el.sourceList.innerHTML = list.map((s, index) => `
      <div class="src-row${s.enabled ? "" : " off"}" data-id="${esc(s.id)}">
        <div class="src-arrow-group" style="display:flex;flex-direction:column;gap:2px">
          <button class="src-arrow" data-move="-1" ${index === 0 ? "disabled" : ""}>▲</button>
          <button class="src-arrow" data-move="1"
                  ${index === list.length - 1 ? "disabled" : ""}>▼</button>
        </div>
        <div class="src-body">
          <div class="src-name">
            ${esc(s.name)}
            <span class="src-badge${s.kind === "link" ? " link" : ""}">
              ${s.kind === "link" ? "跳转" : "API"}${s.builtin ? "" : " · 自定义"}</span>
          </div>
          <div class="src-meta">${esc(s.search_url || s.homepage || "")}</div>
        </div>
        <button class="src-act" data-act="test">测试</button>
        ${s.builtin ? "" : '<button class="src-act danger" data-act="remove">删除</button>'}
        <input type="checkbox" class="switch" data-act="toggle" ${s.enabled ? "checked" : ""}>
      </div>`).join("");
  }

  async function refreshSources() {
    const rows = await call("list_sources");
    state.sources = rows || [];
    renderSources();
    applySourcesHint();
  }

  function applySourcesHint() {
    const enabled = (state.sources || []).filter((s) => s.enabled).length;
    $("sourcesHint").textContent = `${enabled} 个启用`;
  }

  function syncSourceForm() {
    $("srcApiFields").hidden = $("srcKind").value !== "api";
  }

  async function addCustomSource() {
    const name = $("srcName").value.trim();
    const url = $("srcUrl").value.trim();
    if (!name || !url) { toast("名称和搜索地址都要填"); return; }
    const cfg = { name, kind: $("srcKind").value, search_url: url };
    if (cfg.kind === "api") {
      cfg.results_path = $("srcResults").value.trim() || "data";
      const raw = $("srcFields").value.trim();
      if (raw) {
        try {
          cfg.fields = JSON.parse(raw);
        } catch (e) {
          toast("字段映射不是合法的 JSON");
          return;
        }
      } else {
        cfg.fields = {};
      }
    }
    const res = await call("add_custom_source", cfg);
    state.sources = res.sources || state.sources;
    renderSources();
    applySourcesHint();
    el.sourceForm.hidden = true;
    toast("已添加：" + name);
    const test = await call("test_source", res.source.id);
    if (test.kind === "link") toast(`${name} 已添加（跳转型，候选面板里可直接点）`);
    else if (test.ok) toast(`${name} 可用：${test.count} 个结果 · ${(test.sample || []).join(" / ")}`);
    else toast(`${name} 没有返回结果，请检查地址与字段映射`);
  }

  /* ---------------------------------------------------------- 事件：面板开关 */
  const openPanel = (node) => node.classList.add("open");
  const closePanel = (node) => node.classList.remove("open");
  const closeAll = () => {
    closePanel(el.bgPanel); closePanel(el.detailPanel); closePanel(el.matchPanel);
    closePanel(el.sourcePanel);
    closePanel(el.coverPanel); closePanel(el.steamPanel);
    closePanel(el.localePanel);
    closePanel(el.getPanel);
    el.moreMenu.hidden = true;
    el.sortMenu.hidden = true;
    el.addMenu.hidden = true;
  };

  /* ---------------------------------------------------------- 动作 */
  async function importGames() {
    try {
      const res = await call("pick_executable");
      if (!res || res.cancelled) return;
      if (!res.ok) { toast("导入失败：" + (res.error || "未知错误")); return; }
      const games = res.games || [];
      if (!games.length) return;
      await refreshLibrary();
      render();
      setFocus(games[games.length - 1].id);
      closeGame();
      toast(`已导入 ${games.length} 个游戏`);
    } catch (e) { toast("导入失败：" + e.message); }
  }

  async function refreshLibrary() {
    const data = await call("bootstrap");
    state.games = data.games || [];
    state.settings = data.settings || {};
    state.sources = data.sources || [];
    state.version = data.version || "";
    if (state.focus && state.focus !== ADD_KEY && !currentGame()) {
      state.focus = state.games[0]?.id || ADD_KEY;
    }
    applySettingsToUi();
    renderSources();
    applySourcesHint();
  }

  async function togglePlay() {
    const g = currentGame();
    if (!g) return;
    if (g.running) {
      await call("stop", g.id);
      toast("已结束游戏进程");
      return;
    }
    const res = await call("launch", g.id);
    if (!res || !res.ok) {
      const map = {
        "missing-exe": "找不到可执行文件，可能已被移动或删除。",
        "already-running": "游戏已在运行中。",
      };
      toast(map[res && res.error] || "启动失败：" + ((res && res.error) || "未知错误"));
      return;
    }
    toast("游戏已启动");
    const game = state.games.find((x) => x.id === g.id);
    if (game) { game.running = true; render(); }
  }

  async function chooseBackground(url, kind) {
    const g = currentGame();
    if (!g) return;
    g.background = url;
    g.background_kind = kind;
    applyBackground(url, bgViewOf(g));
    renderBgPanel();
    await call("set_background", g.id, url, kind);
  }

  /* 运行中的实时计时（只改那一颗 chip，避免整页重绘） */
  let liveTimer = null;
  function startLiveTicker() {
    if (liveTimer) return;
    liveTimer = setInterval(() => {
      const node = document.getElementById("chipLive");
      if (!node) return;
      const g = currentGame();
      if (!g || !g.running) return;
      node.innerHTML = `运行中 · <b>${clock(sessionSeconds(g))}</b>`;
    }, 1000);
  }

  async function pickLocalBackground() {
    const g = currentGame();
    if (!g) return;
    const res = await call("pick_local_background", g.id);
    if (!res || res.cancelled) return;
    if (!res.ok) { toast("选择失败：" + (res.error || "")); return; }
    Object.assign(g, res.game);
    applyBackground(g.background, bgViewOf(g));
    renderBgPanel();
    toast("已应用本地背景图");
  }

  async function doSearch(query) {
    const g = currentGame();
    if (!g) return;
    state.busy[g.id] = true;
    renderHall();
    renderGameContent();
    try {
      const res = await call("search", g.id, query || null);
      if (res.game) Object.assign(g, res.game);
      state.busy[g.id] = false;
      if (res.ok) {
        closeAll();
        render();
        toast("已匹配：" + g.name);
      } else {
        renderMatches(res.candidates, query);
        $("matchRetry").hidden = Boolean(query);
        openPanel(el.matchPanel);
        render();
        toast(query ? "没有找到匹配结果" : "匹配置信度不足，请手动选择");
      }
    } catch (e) {
      state.busy[g.id] = false;
      renderHall();
      renderGameContent();
      toast("搜索失败：" + e.message);
    }
  }

  async function applyCandidate(item) {
    const g = currentGame();
    if (!g || !item) return;
    toast("正在获取资料…");
    const res = await call("apply_candidate", g.id, item.dataset.source,
                           item.dataset.sourceId, item.dataset.name, "manual");
    if (res.game) Object.assign(g, res.game);
    closeAll();
    render();
    toast("已应用：" + g.name);
  }

  /* ---------------------------------------------------------- 设置 UI */
  /* ---------------------------------------------------------- 设置：网络 */
  async function refreshNetworkPane() {
    try {
      const net = await call("get_network_status");
      if (!net || !net.ok) return;
      $("setProxyMode").value = net.mode || "auto";
      $("setProxyUrl").value = net.url || "";
      $("setProxyFallback").checked = net.fallback !== false;
      el.netStatus.textContent = net.proxy
        ? `当前生效：${net.proxy}（来源：${net.source}）`
        : `当前生效：直连（来源：${net.source || "系统设置"}）`;
    } catch (err) {
      el.netStatus.textContent = "读取代理设置失败：" + err.message;
    }
  }

  function renderNetResults(rows) {
    el.netResults.innerHTML = (rows || []).map((row) => `
      <div class="net-line${row.ok ? " ok" : ""}">
        <i class="dot"></i><span class="name">${esc(row.name)}</span>
        <span class="detail">${esc(row.detail || "")}</span>
      </div>`).join("");
  }

  async function testNetwork() {
    const btn = $("netTest");
    btn.disabled = true;
    el.netResults.innerHTML = '<div class="net-line"><i class="dot"></i><span class="name">正在测试…</span></div>';
    try {
      const res = await call("test_network");
      renderNetResults((res && res.results) || []);
      if (res && res.proxy) {
        el.netStatus.textContent = `当前生效：${res.proxy}（来源：${res.source}）`;
      }
    } catch (err) {
      renderNetResults([{ name: "测试失败", ok: false, detail: err.message }]);
    } finally {
      btn.disabled = false;
    }
  }

  /* ---------------------------------------------------------- 设置：转区启动 */
  const LE_URL = "https://github.com/xupefei/Locale-Emulator/releases";

  async function refreshLocalePane() {
    try {
      const st = await call("get_locale_status");
      state.locale = st || {};
      const proc = (st && st.proc) || "";
      $("setLePath").value = proc;
      $("setLocaleDefault").checked = !!(st && st.default_enabled);
      if (st && st.available) {
        el.leStatus.textContent = `已检测到 Locale Emulator：${proc}`;
      } else if (proc) {
        el.leStatus.textContent = "指定的 LEProc.exe 不可用（缺少运行时文件），请重新选择。";
      } else {
        el.leStatus.textContent = "未检测到 Locale Emulator。装好后点「重新检测」，或手动指定 LEProc.exe。";
      }
      const profiles = (st && st.profiles) || [];
      el.leProfiles.innerHTML = profiles.length
        ? profiles.map((row) => `<span class="src-badge">${esc(row.name || row.guid)}</span>`).join("")
        : (st && st.available
            ? '<span class="hint">没有读到 LEConfig.xml 里的全局配置，转区时会用 LE 的默认配置。</span>'
            : "");
    } catch (err) {
      el.leStatus.textContent = "检测失败：" + err.message;
    }
  }

  /* ---------------------------------------------------------- 转区启动面板（单个游戏） */
  async function renderLocalePanel(game) {
    const g = game || currentGame();
    if (!g) return null;
    $("locSub").textContent = `${g.name} · 转区后以日文区域运行`;
    $("locSwitch").checked = !!g.locale_enabled;
    let st = state.locale || {};
    try {
      st = (await call("get_locale_status")) || st;
      state.locale = st;
    } catch (_) { /* 离线也要能开面板 */ }
    const profiles = st.profiles || [];
    const sel = $("locProfile");
    sel.innerHTML = '<option value="">LE 默认配置</option>'
      + profiles.map((p) =>
          `<option value="${esc(p.guid)}">${esc(p.name || p.guid)}</option>`).join("");
    sel.value = g.locale_guid || "";
    sel.disabled = !st.available;
    const note = $("locStatus");
    if (st.available) {
      note.textContent = profiles.length
        ? `已检测到 Locale Emulator：${st.proc}`
        : `已检测到 Locale Emulator：${st.proc}（没读到 LEConfig.xml，将使用 LE 的默认配置）`;
    } else if (st.proc) {
      note.textContent = "指定的 LEProc.exe 不可用（缺少 LoaderDll.dll / LocaleEmulator.dll 等运行时文件），请重新指定。";
    } else {
      note.textContent = "没有检测到 Locale Emulator。装好并指定 LEProc.exe 后这里就会生效；"
        + "没装也不影响启动，只是会按系统区域运行（日文原版可能出现乱码）。";
    }
    return st;
  }

  async function openLocalePanel() {
    const g = currentGame();
    if (!g) return;
    closeAll();
    await renderLocalePanel(g);
    openPanel(el.localePanel);
  }

  /* 写回单个游戏的转区开关与配置 */
  async function saveGameLocale(enabled, guid) {
    const g = currentGame();
    if (!g) return;
    const res = await call("set_game_locale", g.id, !!enabled, guid || "");
    if (!res || !res.ok) { toast("保存转区设置失败"); return; }
    if (res.game) Object.assign(g, res.game);
    render();
    const usable = state.locale && state.locale.available;
    toast(enabled
      ? (usable ? "已开启转区启动" : "已开启：装好 Locale Emulator 后即可生效")
      : "已关闭转区启动");
  }

  function applySettingsToUi() {
    const s = state.settings;
    document.documentElement.style.setProperty("--blur", (s.blur ?? 30) + "px");
    document.documentElement.style.setProperty("--sat", (s.saturation ?? 190) + "%");
    document.documentElement.style.setProperty("--scrim", String(s.scrim ?? 42) / 100);
    if (s.accent) document.documentElement.style.setProperty("--accent", s.accent);

    $("setBlur").value = s.blur ?? 30;
    $("setScrim").value = s.scrim ?? 42;
    $("setAccent").value = s.accent || "#0A84FF";
    $("setSat").value = s.saturation ?? 190;
    $("setKen").checked = !!s.ken_burns;
    $("setLang").value = s.lang || "schinese";
    $("setMerge").checked = s.sources ? s.sources.merge_images !== false : true;
    $("setTray").checked = !!s.close_to_tray;
    $("setTransEnabled").checked = s.translate_enabled !== false;
    $("setTransProvider").value = s.translate_provider || "auto";
    $("setTransBase").value = s.translate_base_url || "";
    $("setTransKey").value = s.translate_api_key || "";
    $("setTransModel").value = s.translate_model || "";
    $("setShowOriginal").checked = !!s.show_original;
    $("setBlurVal").textContent = (s.blur ?? 30) + "px";
    $("setScrimVal").textContent = (s.scrim ?? 42) + "%";
    $("setSatVal").textContent = (s.saturation ?? 190) + "%";
  }

  async function saveSetting(key, value) {
    state.settings[key] = value;
    applySettingsToUi();
    if (key === "ken_burns") {
      const inner = bgLayer().querySelector(".bg-img");
      if (inner) inner.classList.toggle("ken", !!value);
    }
    await call("set_setting", key, value);
  }

  /* ---------------------------------------------------------- 窗口拖拽 / 缩放 */
  function bindWindowControls() {
    $("btnMin").onclick = () => call("window_cmd", "minimize");
    $("btnMax").onclick = () => call("window_cmd", "toggle_maximize");
    $("btnClose").onclick = () => call("window_cmd", "close");

    document.addEventListener("mousedown", async (e) => {
      if (e.button !== 0) return;

      const rz = e.target.closest(".rz");
      if (rz) {
        e.preventDefault();
        resize = { edge: rz.dataset.edge, sx: e.screenX, sy: e.screenY, base: null, queued: false };
        resize.base = await call("resize_start");
        return;
      }

      const handle = e.target.closest("[data-drag]");
      if (!handle) return;
      if (e.target.closest("[data-nodrag],button,input,select,textarea,a,.gi,.bg-item,.match-item")) return;
      e.preventDefault();
      drag = { sx: e.screenX, sy: e.screenY, queued: false };
      await call("drag_start");
    });

    document.addEventListener("mousemove", (e) => {
      if (resize && resize.base) {
        if (resize.queued) return;
        resize.queued = true;
        const sx = e.screenX, sy = e.screenY;
        requestAnimationFrame(() => {
          resize.queued = false;
          if (!resize || !resize.base) return;
          const d = window.devicePixelRatio || 1;
          const dx = (sx - resize.sx) * d;
          const dy = (sy - resize.sy) * d;
          const b = resize.base;
          let { x, y, w, h } = b;
          if (resize.edge.includes("e")) w = b.w + dx;
          if (resize.edge.includes("s")) h = b.h + dy;
          if (resize.edge.includes("w")) { w = b.w - dx; x = b.x + dx; }
          if (resize.edge.includes("n")) { h = b.h - dy; y = b.y + dy; }
          call("resize_apply", Math.round(x), Math.round(y), Math.round(w), Math.round(h),
               resize.edge);
        });
        return;
      }
      if (drag) {
        if (drag.queued) return;
        drag.queued = true;
        const dx = e.screenX - drag.sx;
        const dy = e.screenY - drag.sy;
        requestAnimationFrame(() => {
          drag.queued = false;
          if (drag) call("drag_move", dx * (window.devicePixelRatio || 1),
                         dy * (window.devicePixelRatio || 1));
        });
      }
    });

    document.addEventListener("mouseup", () => {
      if (drag) { drag = null; call("drag_end"); }
      if (resize) { resize = null; }
      if (swipe) swipe = null;
    });

    // 双击拖拽区域最大化 / 还原
    document.addEventListener("dblclick", (e) => {
      if (e.target.closest("[data-drag]") &&
          !e.target.closest("[data-nodrag],button,input,select,a,.gi")) {
        call("window_cmd", "toggle_maximize");
      }
    });
  }

  /* ---------------------------------------------------------- 背景缩放 / 图片回退 */
  function bindBgView() {
    // 图片加载失败 -> 依次尝试备用地址，全部失败则显示占位
    document.addEventListener("error", (e) => {
      const img = e.target;
      if (!img || img.tagName !== "IMG" || !img.dataset) return;
      let chain = [];
      try { chain = JSON.parse(img.dataset.srcs || "[]"); } catch (_) { chain = []; }
      if (chain.length) {
        img.dataset.srcs = JSON.stringify(chain.slice(1));
        img.src = chain[0];
        return;
      }
      img.classList.add("img-broken");
      const holder = img.parentElement;
      if (holder) holder.classList.add("img-broken");
      const item = img.closest(".bg-item, .gi-cover");
      if (item) item.classList.add("img-broken");
    }, true);

    // 面板里的缩放滑杆
    $("bgZoom").oninput = (e) => {
      const g = currentGame();
      if (!g) return;
      updateBgView({ scale: Number(e.target.value) / 100 }, false);
    };
    $("bgZoom").onchange = (e) => {
      const g = currentGame();
      if (!g) return;
      updateBgView({ scale: Number(e.target.value) / 100 });
    };
    $("bgViewReset").onclick = () => {
      updateBgView({ scale: 1 });
      toast("背景已复位");
    };

    // 滚轮 / 横向滚动 = 切换游戏（大厅与游戏页一致）
    $("app").addEventListener("wheel", (e) => {
      if (e.target.closest(".sheet, .menu, .modal, input, select, textarea, #toolbar, #toast")) return;
      if (!state.games.length) return;
      e.preventDefault();
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      const now = Date.now();
      if (now - (bindBgView._last || 0) < 130) return;
      if (Math.abs(delta) < 2) return;
      bindBgView._last = now;
      moveFocus(delta > 0 ? 1 : -1);
    }, { passive: false });
  }

  /* ---------------------------------------------------------- 绑定 */
  /* 排序菜单里的选中态 */
  function syncSortMenu() {
    for (const btn of el.sortMenu.querySelectorAll("button[data-sort]")) {
      btn.classList.toggle("on", btn.dataset.sort === state.sort);
    }
  }

  /* 末尾方块的二选一菜单：导入本地 / 获取游戏 */
  function openAddMenu(tile) {
    const rect = tile.getBoundingClientRect();
    el.addMenu.hidden = false;
    const box = el.addMenu.getBoundingClientRect();
    let left = Math.round(rect.left + rect.width / 2 - box.width / 2);
    left = Math.max(12, Math.min(window.innerWidth - box.width - 12, left));
    let top = Math.round(rect.top - box.height - 10);
    if (top < 80) top = Math.round(rect.bottom + 10);
    el.addMenu.style.left = left + "px";
    el.addMenu.style.top = top + "px";
  }

  function bindUi() {
    $("btnImport2").onclick = importGames;
    el.play.onclick = togglePlay;
    el.btnBack.onclick = closeGame;

    // 大厅：单击进入 / 双击启动 / 悬停聚焦 / 横向滑动切换
    let hoverTimer = null;
    let moved = false;
    el.hallRow.addEventListener("mousemove", (e) => {
      const tile = e.target.closest(".gi");
      if (!tile) return;
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => {
        const key = tile.dataset.add ? ADD_KEY : tile.dataset.id;
        if (key && key !== state.focus) setFocus(key);
      }, 320);
    });
    el.hallRow.addEventListener("mouseleave", () => clearTimeout(hoverTimer));
    el.hallRow.addEventListener("click", (e) => {
      const tile = e.target.closest(".gi");
      if (!tile || moved) return;
      if (tile.dataset.add) { openAddMenu(tile); return; }
      const id = tile.dataset.id;
      if (state.focus !== id) setFocus(id);
      openGame(id);
    });
    el.hallRow.addEventListener("dblclick", (e) => {
      const tile = e.target.closest(".gi");
      if (!tile || tile.dataset.add) return;
      setFocus(tile.dataset.id);
      openGame(tile.dataset.id);
      togglePlay();
    });

    // 横向拖动 = 换一张封面
    const swipeStart = (e) => {
      if (e.button !== 0) return;
      // 工具条 / 底部信息带是拖窗口的区域，别在这里抢滑动
      if (e.target.closest("button, a, input, .pill, [data-drag], .rz")) return;
      swipe = { x: e.clientX, y: e.clientY, base: e.clientX };
      moved = false;
    };
    const swipeMove = (e) => {
      if (!swipe) return;
      const dx = e.clientX - swipe.base;
      const dy = e.clientY - swipe.y;
      if (Math.abs(dx) < 64 || Math.abs(dy) > Math.abs(dx)) return;
      moved = true;
      swipe.base = e.clientX;
      moveFocus(dx < 0 ? 1 : -1);
    };
    $("app").addEventListener("mousedown", swipeStart);
    document.addEventListener("mousemove", swipeMove);

    // 窗口尺寸变化后重新把焦点封面摆到正中
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => updateRow(true), 80);
    });

    $("btnBackgrounds").onclick = () => {
      const opening = !el.bgPanel.classList.contains("open");
      closeAll();
      if (opening) { renderBgPanel(); openPanel(el.bgPanel); }
    };
    $("bgClose").onclick = () => closePanel(el.bgPanel);
    el.bgGrid.addEventListener("click", (e) => {
      const item = e.target.closest(".bg-item");
      if (item) chooseBackground(item.dataset.url, item.dataset.kind);
    });
    $("btnLocalBg").onclick = pickLocalBackground;
    $("btnResetBg").onclick = async () => {
      const g = currentGame();
      if (!g) return;
      const res = await call("clear_background", g.id);
      if (res.game) Object.assign(g, res.game);
      const first = (g.images || [])[0];
      if (first) { g.background = first.url; g.background_kind = first.kind; }
      g.bg_scale = 1; g.bg_x = 0; g.bg_y = 0;
      applyBackground(g.background || fallbackBackground(g), { scale: 1, x: 0, y: 0 });
      syncBgZoomUi(g);
      renderBgPanel();
    };

    $("btnDetails").onclick = () => {
      const opening = !el.detailPanel.classList.contains("open");
      closeAll();
      if (opening) { renderDetail(); openPanel(el.detailPanel); }
    };
    $("detailClose").onclick = () => closePanel(el.detailPanel);
    el.detailBody.addEventListener("click", (e) => {
      const link = e.target.closest("a[data-url]");
      if (link) { call("open_url", link.dataset.url); return; }
      const shot = e.target.closest(".shot");
      if (shot) {
        chooseBackground(shot.dataset.shot, shot.dataset.kind || "screenshot");
        toast("已设为背景");
      }
    });

    $("matchClose").onclick = () => closePanel(el.matchPanel);
    $("matchGo").onclick = () => doSearch(el.matchQuery.value.trim());
    el.matchQuery.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch(el.matchQuery.value.trim());
    });
    el.matchList.addEventListener("click", (e) => {
      const item = e.target.closest(".match-item");
      if (item) applyCandidate(item);
    });
    el.matchLinks.addEventListener("click", (e) => {
      const chip = e.target.closest("[data-link-source]");
      if (!chip) return;
      const query = el.matchQuery.value.trim();
      if (!query) { toast("先输入要搜索的名字"); return; }
      call("open_source_search", query, chip.dataset.linkSource).then((res) => {
        if (!res || !res.ok) toast("打不开搜索页：" + ((res && res.error) || ""));
      });
    });

    // 更多菜单
    $("btnMore").onclick = () => {
      const hidden = el.moreMenu.hidden;
      closeAll();
      const g = currentGame();
      $("menuIconReset").hidden = !(g && g.custom_icon);
      $("menuNameReset").hidden = !(g && g.name_locked);
      $("menuFavorite").textContent = g && g.favorite ? "取消收藏" : "加入收藏";
      $("menuLocale").textContent = g && g.locale_enabled
        ? "转区设置（已开启）…" : "转区启动…";
      el.moreMenu.hidden = !hidden;
    };
    el.moreMenu.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-act]");
      if (!btn) return;
      const g = currentGame();
      el.moreMenu.hidden = true;
      if (!g) return;
      const act = btn.dataset.act;
      if (act === "reveal") { call("reveal", g.id); }
      else if (act === "favorite") {
        const res = await call("toggle_favorite", g.id);
        if (res.game) Object.assign(g, res.game);
        render();
        toast(res.favorite ? "已加入收藏" : "已取消收藏");
      }
      else if (act === "rename") {
        const value = await modal({
          title: "重命名", body: "只改启动器里显示的名字，不动游戏文件。",
          input: true, value: g.name, okText: "保存",
        });
        if (value === null) return;
        if (!value) { toast("名字不能为空"); return; }
        const res = await call("rename_game", g.id, value);
        if (res.game) Object.assign(g, res.game);
        render();
        toast("已重命名");
      }
      else if (act === "name-reset") {
        const res = await call("reset_name", g.id);
        if (res.game) Object.assign(g, res.game);
        render();
        toast("已恢复自动命名，正在重新搜索…");
      }
      else if (act === "cover") { openCoverPanel(); }
      else if (act === "icon") {
        const res = await call("pick_custom_icon", g.id);
        if (!res || res.cancelled) return;
        if (!res.ok) { toast("设置图标失败：" + (res.error || "")); return; }
        Object.assign(g, res.game);
        render();
        toast("已设置自定义图标");
      } else if (act === "icon-reset") {
        const res = await call("clear_custom_icon", g.id);
        if (res.game) Object.assign(g, res.game);
        render();
        toast("已恢复默认图标");
      } else if (act === "store") {
        if (g.source_url) call("open_url", g.source_url);
        else toast("还没有匹配到条目");
      } else if (act === "research") { doSearch(null); }
      else if (act === "locale") { openLocalePanel(); }
      else if (act === "translate") {
        const res = await call("translate_game", g.id);
        if (!res || !res.ok) { toast("翻译启动失败"); return; }
        toast("正在翻译简介…");
      }
      else if (act === "args") {
        const value = await modal({
          title: "启动参数", body: "会追加在可执行文件之后，点下面的常用参数可快速加入。",
          input: true, value: g.launch_args || "", okText: "保存",
          presets: ["-windowed", "-fullscreen", "-dx11", "-dx12", "-novid", "-high"],
        });
        if (value !== null) {
          g.launch_args = value;
          await call("set_launch_args", g.id, value);
          toast("已保存启动参数");
        }
      } else if (act === "remove") {
        const ok = await modal({
          title: "移除游戏",
          body: `确定把「${g.name}」从库中移除吗？不会删除磁盘上的文件。`,
          okText: "移除",
        });
        if (!ok) return;
        await call("remove_game", g.id);
        await refreshLibrary();
        if (state.focus === g.id) {
          state.focus = state.games[0]?.id || ADD_KEY;
          if (state.page === "game") closeGame();
        }
        render();
        toast("已移除");
      }
    });

    // 设置
    $("btnSettings").onclick = () => openSettings();
    $("setBack").onclick = closeSettings;
    el.setNav.addEventListener("click", (e) => {
      const tab = e.target.closest(".set-tab");
      if (tab) setSettingsTab(tab.dataset.pane);
    });

    // 设置 → 网络
    $("setProxyMode").onchange = async (e) => {
      await call("set_proxy_option", "proxy_mode", e.target.value);
      toast(e.target.value === "direct" ? "已切换为直连" : "代理设置已保存");
      refreshNetworkPane();
    };
    $("setProxyUrl").onchange = async (e) => {
      const res = await call("set_proxy_option", "proxy_url", e.target.value.trim());
      if (res && res.ok === false) toast("代理地址无效：" + (res.error || ""));
      refreshNetworkPane();
    };
    $("setProxyFallback").onchange = async (e) => {
      await call("set_proxy_option", "proxy_fallback", e.target.checked);
    };
    $("netTest").onclick = testNetwork;

    // 设置 → 转区启动
    $("setLocaleDefault").onchange = async (e) => {
      await call("set_locale_option", "locale_default", e.target.checked);
      toast(e.target.checked ? "新导入的游戏默认开启转区" : "已关闭默认转区");
    };
    $("setLePick").onclick = async () => {
      const res = await call("pick_locale_proc");
      if (!res || res.cancelled) return;
      if (!res.ok) { toast("这个路径不可用：" + ((res && res.error) || "")); return; }
      await refreshLocalePane();
      toast("已设置 Locale Emulator 路径");
    };
    $("setLeRefresh").onclick = refreshLocalePane;
    $("setLeDownload").onclick = () => call("open_url", LE_URL);
    $("btnOpenData").onclick = () => call("open_data_dir");

    // 转区启动面板（单个游戏）
    $("locClose").onclick = () => closePanel(el.localePanel);
    $("locSwitch").onchange = (e) => saveGameLocale(e.target.checked, $("locProfile").value);
    $("locProfile").onchange = (e) => saveGameLocale($("locSwitch").checked, e.target.value);
    $("locPick").onclick = async () => {
      const res = await call("pick_locale_proc");
      if (!res || res.cancelled) return;
      if (!res.ok) { toast("这个路径不可用：" + ((res && res.error) || "")); return; }
      await renderLocalePanel();
      toast("已设置 Locale Emulator 路径");
    };
    $("locDownload").onclick = () => call("open_url", LE_URL);

    $("setBlur").oninput = (e) => {
      state.settings.blur = Number(e.target.value);
      applySettingsToUi();
    };
    $("setBlur").onchange = (e) => saveSetting("blur", Number(e.target.value));
    $("setScrim").oninput = (e) => {
      state.settings.scrim = Number(e.target.value);
      applySettingsToUi();
    };
    $("setScrim").onchange = (e) => saveSetting("scrim", Number(e.target.value));
    $("setAccent").oninput = (e) => {
      state.settings.accent = e.target.value;
      applySettingsToUi();
    };
    $("setAccent").onchange = (e) => saveSetting("accent", e.target.value);
    $("setSat").oninput = (e) => {
      state.settings.saturation = Number(e.target.value);
      applySettingsToUi();
    };
    $("setSat").onchange = (e) => saveSetting("saturation", Number(e.target.value));
    $("setKen").onchange = (e) => saveSetting("ken_burns", e.target.checked);
    $("setLang").onchange = (e) => saveSetting("lang", e.target.value);
    $("setMerge").onchange = async (e) => {
      const res = await call("set_merge_sources", e.target.checked);
      if (state.settings.sources) state.settings.sources.merge_images = res.merge_images;
      toast(e.target.checked ? "已开启多源补图" : "已关闭多源补图");
    };
    $("btnSources").onclick = async () => {
      closeAll();
      await refreshSources();
      openPanel(el.sourcePanel);
    };
    $("setTray").onchange = async (e) => {
      await saveSetting("close_to_tray", e.target.checked);
      toast(e.target.checked
        ? "已开启：关窗口时缩到托盘，游戏继续跑"
        : "已关闭：关窗口即退出");
    };
    $("btnSteamScan").onclick = openSteamPanel;
    $("btnRefreshAll").onclick = startRefreshAll;
    $("btnTranslateAll").onclick = startTranslateAll;
    $("setTransEnabled").onchange = (e) => saveSetting("translate_enabled", e.target.checked);
    $("setTransProvider").onchange = (e) => saveSetting("translate_provider", e.target.value);
    $("setTransBase").onchange = (e) => saveSetting("translate_base_url", e.target.value.trim());
    $("setTransKey").onchange = (e) => saveSetting("translate_api_key", e.target.value.trim());
    $("setTransModel").onchange = (e) => saveSetting("translate_model", e.target.value.trim());
    $("setShowOriginal").onchange = async (e) => { await saveSetting("show_original", e.target.checked); render(); };
    $("transTest").onclick = async () => {
      const status = $("transStatus");
      status.textContent = "测试中…";
      const res = await call("test_translation", {
        translate_provider: $("setTransProvider").value,
        translate_base_url: $("setTransBase").value.trim(),
        translate_api_key: $("setTransKey").value.trim(),
        translate_model: $("setTransModel").value.trim(),
      });
      if (res && res.ok) {
        status.textContent = `可用（${res.provider}）：${res.text}`;
        toast("翻译接口可用");
      } else {
        status.textContent = "不可用：" + ((res && res.error) || "未知错误");
        toast("翻译接口不可用");
      }
    };
    $("btnShowOriginal").onclick = async () => {
      await saveSetting("show_original", !state.settings.show_original);
      render();
    };
    $("btnExport").onclick = async () => {
      const res = await call("export_library");
      if (!res || res.cancelled) return;
      if (!res.ok) { toast("导出失败：" + ((res && res.error) || "")); return; }
      toast(`已导出 ${res.games} 个游戏到 ${res.path.split("\\").pop()}`, 4200);
    };
    $("btnImportLib").onclick = async () => {
      const res = await call("import_library");
      if (!res || res.cancelled) return;
      if (!res.ok) {
        toast(res && res.error === "bad-file" ? "这个文件不是 Aurora 导出的游戏库" : "导入失败");
        return;
      }
      await refreshLibrary();
      render();
      toast(`导入完成：新增 ${res.added} 个，跳过 ${res.skipped} 个`);
    };

    // 封面面板
    $("coverClose").onclick = () => closePanel(el.coverPanel);
    el.coverGrid.addEventListener("click", async (e) => {
      const item = e.target.closest("[data-cover]");
      if (!item) return;
      const g = currentGame();
      if (!g) return;
      const res = await call("set_cover", g.id, item.dataset.cover);
      if (res.game) Object.assign(g, res.game);
      renderCoverPanel();
      render();
      toast("已更换封面");
    });
    $("btnLocalCover").onclick = async () => {
      const g = currentGame();
      if (!g) return;
      const res = await call("pick_local_cover", g.id);
      if (!res || res.cancelled) return;
      if (!res.ok) { toast("选择失败：" + ((res && res.error) || "")); return; }
      Object.assign(g, res.game);
      renderCoverPanel();
      render();
      toast("已应用本地封面");
    };
    $("btnCoverReset").onclick = async () => {
      const g = currentGame();
      if (!g) return;
      const res = await call("clear_custom_cover", g.id);
      if (res.game) Object.assign(g, res.game);
      renderCoverPanel();
      render();
      toast("已恢复默认封面");
    };

    // Steam 面板
    $("steamClose").onclick = () => closePanel(el.steamPanel);
    $("steamAll").onclick = () => {
      (state.steam || []).forEach((row) => { if (!row.already) state.picked.add(row.exe); });
      renderSteamList();
    };
    $("steamNone").onclick = () => { state.picked.clear(); renderSteamList(); };
    $("steamImport").onclick = importSteam;
    el.steamList.addEventListener("change", (e) => {
      const box = e.target.closest("input[data-exe]");
      if (!box) return;
      if (box.checked) state.picked.add(box.dataset.exe);
      else state.picked.delete(box.dataset.exe);
      updateSteamHint();
    });
    $("matchRetry").onclick = () => doSearch(null);

    // 获取游戏（下载大厅）
    $("btnGetGames").onclick = openGetPanel;
    $("getClose").onclick = () => closePanel(el.getPanel);
    $("getChangeDir").onclick = async () => {
      const res = await call("pick_download_dir");
      if (!res || res.cancelled) return;
      if (!res.ok) { toast("设置失败：" + ((res && res.error) || "")); return; }
      await refreshDownloadSettings();
      toast("下载目录已更新");
    };
    $("getOpenDir").onclick = () => call("open_download_dir");
    $("getWatch").onchange = async (e) => {
      await call("set_download_option", "download_watch", e.target.checked);
      await refreshDownloadSettings();
      toast(e.target.checked ? "已开启下载目录监听" : "已暂停下载目录监听");
    };
    $("getExtract").onchange = async (e) => {
      await call("set_download_option", "download_extract", e.target.checked);
      await refreshDownloadSettings();
    };
    $("getScan").onclick = async () => {
      const res = await call("scan_downloads");
      await refreshDownloadSettings();
      if (!res || !res.ok) { toast("扫描失败"); return; }
      const n = res.imported || 0;
      toast(n ? `扫描完成：导入 ${n} 个游戏` : "扫描完成：没有发现新的游戏");
      if (n) { await refreshLibrary(); render(); }
    };
    $("getAddSite").onclick = () => {
      el.getSiteForm.hidden = false;
      $("getSiteName").value = "";
      $("getSiteUrl").value = "";
      $("getSiteName").focus();
    };
    $("getSiteCancel").onclick = () => { el.getSiteForm.hidden = true; };
    $("getSiteSave").onclick = addSite;
    $("getSiteUrl").addEventListener("keydown", (e) => {
      if (e.key === "Enter") addSite();
    });
    el.getSites.addEventListener("click", async (e) => {
      const open = e.target.closest("button[data-site]");
      if (open) { openSite(open.dataset.site); return; }
      const del = e.target.closest("button[data-del]");
      if (!del) return;
      const res = await call("remove_site", del.dataset.del);
      state.sites = (res && res.sites) || [];
      renderSites();
      toast("已删除该资源站");
    });
    el.addMenu.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-add-act]");
      if (!btn) return;
      el.addMenu.hidden = true;
      if (btn.dataset.addAct === "import") importGames();
      else openGetPanel();
    });

    // 资料源管理
    $("sourceClose").onclick = () => closePanel(el.sourcePanel);
    $("srcAdd").onclick = () => {
      el.sourceForm.hidden = false;
      $("srcName").value = "";
      $("srcUrl").value = "";
      $("srcResults").value = "";
      $("srcFields").value = "";
      $("srcKind").value = "api";
      syncSourceForm();
      $("srcName").focus();
    };
    $("srcCancel").onclick = () => { el.sourceForm.hidden = true; };
    $("srcKind").onchange = syncSourceForm;
    $("srcSave").onclick = addCustomSource;
    el.sourceList.addEventListener("click", async (e) => {
      const row = e.target.closest(".src-row");
      if (!row) return;
      const id = row.dataset.id;
      const arrow = e.target.closest("[data-move]");
      if (arrow) {
        const res = await call("move_source", id, Number(arrow.dataset.move));
        state.sources = res.sources || state.sources;
        renderSources();
        return;
      }
      const act = e.target.closest("[data-act]");
      if (!act) return;
      if (act.dataset.act === "test") {
        act.textContent = "测试中";
        const res = await call("test_source", id);
        act.textContent = "测试";
        if (res.kind === "link") toast("这是跳转型源，点击候选面板里的按钮使用");
        else if (res.ok) toast(`可用：${res.count} 个结果 · ${res.elapsed}s · ${(res.sample || []).join(" / ")}`);
        else toast("没有返回结果：" + (res.error || ""));
      } else if (act.dataset.act === "remove") {
        const res = await call("remove_custom_source", id);
        state.sources = res.sources || state.sources;
        renderSources();
        applySourcesHint();
        toast("已删除");
      }
    });
    el.sourceList.addEventListener("change", async (e) => {
      const toggle = e.target.closest("[data-act='toggle']");
      if (!toggle) return;
      const row = toggle.closest(".src-row");
      const res = await call("toggle_source", row.dataset.id, toggle.checked);
      state.sources = res.sources || state.sources;
      renderSources();
      applySourcesHint();
    });

    // 搜索过滤
    el.search.oninput = (e) => {
      state.filter = e.target.value;
      el.searchClear.hidden = !state.filter;
      renderHall();
    };
    el.searchClear.onclick = () => {
      el.search.value = ""; state.filter = ""; el.searchClear.hidden = true; renderHall();
    };
    el.search.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const first = visibleGames()[0];
        if (first) { setFocus(first.id); openGame(first.id); }
      }
    });

    // 排序（工具条图标 → 菜单）
    $("btnSort").onclick = () => {
      const hidden = el.sortMenu.hidden;
      closeAll();
      // 菜单右边缘对齐排序按钮，换窗口宽度也不会错位
      const btn = $("btnSort").getBoundingClientRect();
      el.sortMenu.style.right = Math.round(window.innerWidth - btn.right) + "px";
      el.sortMenu.hidden = !hidden;
      syncSortMenu();
    };
    el.sortMenu.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-sort]");
      if (!btn) return;
      state.sort = btn.dataset.sort;
      el.sortMenu.hidden = true;
      renderHall();
      const game = currentGame();
      if (game) setFocus(game.id);
    });

    // 全局
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#moreMenu, #btnMore")) el.moreMenu.hidden = true;
      if (!e.target.closest("#sortMenu, #btnSort")) el.sortMenu.hidden = true;
      if (!e.target.closest("#addMenu, .gi-add")) el.addMenu.hidden = true;
    });
    document.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.target?.isContentEditable;
      if (e.key === "Escape") {
        const anyOpen = [el.bgPanel, el.detailPanel, el.matchPanel, el.sourcePanel,
                         el.coverPanel, el.steamPanel, el.localePanel, el.getPanel]
          .some((p) => p.classList.contains("open"));
        const menuOpen = !el.moreMenu.hidden || !el.sortMenu.hidden || !el.addMenu.hidden;
        if (anyOpen || menuOpen) { closeAll(); return; }
        if (state.settingsOpen) { closeSettings(); return; }
        if (state.page === "game") { closeGame(); return; }
      }
      if (e.key === "F5" || (e.ctrlKey && e.key.toLowerCase() === "r")) e.preventDefault();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        el.search.focus();
        el.search.select();
        return;
      }
      if (typing || !el.modal.hidden) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); moveFocus(-1); return; }
      if (e.key === "ArrowRight") { e.preventDefault(); moveFocus(1); return; }
      if (e.key === "Home") { e.preventDefault(); jumpFocus("start"); return; }
      if (e.key === "End") { e.preventDefault(); jumpFocus("end"); return; }
      if (e.key === "Enter") {
        e.preventDefault();
        if (state.page === "game") togglePlay();
        else if (state.focus === ADD_KEY) {
          const tile = document.querySelector("#hallRow .gi-add");
          if (tile) openAddMenu(tile);
        } else openGame();
      }
    });
    document.addEventListener("contextmenu", (e) => {
      if (!e.target.closest("input,textarea,[contenteditable]")) e.preventDefault();
    });
    // 拖放：真正的导入由后端（main.py 注册的 drop 监听）完成，
    // 这里只负责显示提示层、并阻止浏览器把文件当页面打开。
    const hasFiles = (e) => {
      const types = (e.dataTransfer && e.dataTransfer.types) || [];
      return Array.prototype.indexOf.call(types, "Files") >= 0;
    };
    let dragDepth = 0;
    document.addEventListener("dragenter", (e) => {
      if (!hasFiles(e)) return;
      dragDepth += 1;
      el.dropHint.hidden = false;
    });
    document.addEventListener("dragover", (e) => {
      if (hasFiles(e)) e.preventDefault();
    });
    document.addEventListener("dragleave", (e) => {
      if (!hasFiles(e)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) el.dropHint.hidden = true;
    });
    document.addEventListener("drop", (e) => {
      dragDepth = 0;
      el.dropHint.hidden = true;
      e.preventDefault();
    });
  }

  /* ---------------------------------------------------------- 推送事件 */
  /* 转区启动的落点提示：LE 没装或带不动时照样启动，只说明一句 */
  function notifyLocaleStart(mode) {
    if (mode === "no-le") {
      toast("没检测到 Locale Emulator，已按普通方式启动", 4600);
    } else if (mode === "unsupported-target") {
      toast("目标不是 32 位 exe，Locale Emulator 带不动，已按普通方式启动", 4600);
    } else if (mode === "locale") {
      toast("已用指定的 LE 配置转区启动");
    } else if (mode === "locale-default") {
      toast("已用 LE 默认配置转区启动");
    }
  }

  /* 搜索结束却没有封面：说明图片是界面侧加载（走系统代理），同一个游戏只提醒一次 */
  const coverHinted = new Set();
  function hintCoverOnce(game) {
    if (!game || !game.id || coverHinted.has(game.id)) return;
    if (game.cover || game.custom_cover || (game.cover_sources || []).length) return;
    coverHinted.add(game.id);
    toast("没抓到封面：图片由界面直接加载（走系统代理），可在「设置 → 网络」测试连通性", 5400);
  }

  window.__aurora = {
    emit(event, payload) {
      try {
        if (event === "game:updated" || event === "game:stopped" || event === "game:running") {
          const idx = state.games.findIndex((g) => g.id === payload.id);
          let isNew = false;
          if (idx >= 0) {
            const running = event === "game:running" ? true
              : event === "game:stopped" ? false : payload.running;
            state.games[idx] = { ...state.games[idx], ...payload, running };
          } else if (payload && payload.id) {
            state.games.push(payload);
            isNew = true;
          }
          delete state.busy[payload.id];
          render();
          if (event === "game:running") notifyLocaleStart(payload.locale);
          if (event === "game:updated" && payload.metadata_state === "ok") hintCoverOnce(payload);
          // 库里原本没有这个游戏（导入/拖放）时，把焦点挪过去并换上它的壁纸
          if (isNew && !currentGame()) setFocus(payload.id);
          // 当前游戏换了壁纸（背景面板 / 其它来源）时跟着换
          else if (payload.id === state.focus) scheduleBackground();
        } else if (event === "metadata:searching") {
          state.busy[payload.id] = true;
          renderHall();
        } else if (event === "games:imported") {
          // 拖放/导入进来的游戏：并进大厅并聚焦最后一个
          (payload.games || []).forEach((g) => {
            const idx = state.games.findIndex((x) => x.id === g.id);
            if (idx >= 0) state.games[idx] = { ...state.games[idx], ...g };
            else state.games.push(g);
          });
          const ids = payload.ids || [];
          render();
          if (ids.length) setFocus(ids[ids.length - 1]);
          const ignored = payload.ignored || 0;
          toast(ids.length ? `已导入 ${ids.length} 个游戏` : "没有可导入的 exe"
                + (ignored ? "（已忽略非 exe 文件）" : ""), ids.length ? 2600 : 4000);
        } else if (event === "metadata:notfound") {
          delete state.busy[payload.id];
          let g = state.games.find((x) => x.id === payload.id);
          if (!g && payload.game) {
            state.games.push(payload.game);
            if (!currentGame()) state.focus = payload.id;
            g = payload.game;
          }
          if (g) { g.metadata_state = "notfound"; g.metadata_note = payload.note; }
          render();
          // 只有正看着这个游戏时才弹候选面板；在大厅里只提示，不打断浏览
          if (state.focus === payload.id && state.page === "game" && !payload.quiet) {
            renderMatches(payload.candidates, "");
            $("matchRetry").hidden = !/网络/.test(payload.note || "");
            openPanel(el.matchPanel);
            toast(payload.note || "没有找到匹配结果");
          } else if (g && !payload.quiet) {
            toast(`${g.name}：${payload.note || "没有找到匹配结果"}`, 3600);
          }
        } else if (event === "batch:progress") {
          const batch = state.batch;
          if (!batch) return;
          batch.done = payload.done;
          batch.total = payload.total;
          if (batch.kind === "steam") {
            el.steamImport.textContent = `导入中 ${payload.done}/${payload.total}`;
          } else if (batch.kind === "translate") {
            $("translateHint").textContent = `${payload.done}/${payload.total}`;
          } else {
            $("refreshHint").textContent = `${payload.done}/${payload.total}`;
          }
        } else if (event === "batch:done") {
          const batch = state.batch;
          state.batch = null;
          $("refreshHint").textContent = "";
          $("translateHint").textContent = "";
          if (batch && batch.kind === "steam") {
            updateSteamHint();
            toast(`Steam 导入完成：${payload.imported || 0} 个游戏`);
            refreshLibrary().catch(() => {});
          } else if (batch && batch.kind === "translate") {
            toast(`简介翻译完成：翻译 ${payload.translated || 0} 个，跳过 ${payload.skipped || 0} 个`
              + (payload.failed ? `，失败 ${payload.failed} 个` : ""), 4200);
            refreshLibrary().catch(() => {});
          } else {
            toast(`已重新抓取 ${payload.total} 个游戏的信息`);
          }
        } else if (event === "metadata:error") {
          delete state.busy[payload.id];
          render();
          toast("搜索出错：" + payload.note);
        } else if (event === "translate:done") {
          // 只有手动点「翻译简介」才回执，自动翻译安静进行
          if (!payload.manual) return;
          if (payload.changed) {
            toast(payload.provider === "llm" ? "已用 LLM 翻译简介" : "已用免费接口翻译简介");
          } else if (payload.error === "empty") {
            toast("这款游戏还没有简介可翻译");
          } else if (payload.error === "stale") {
            toast("简介刚被更新，请再翻译一次");
          } else if (payload.error === "busy") {
            toast("正在翻译中…");
          } else if (payload.error) {
            toast("翻译失败：" + payload.error);
          } else {
            toast("简介已经是中文，无需翻译");
          }
        } else if (event === "downloads:status") {
          if (payload.kind === "warn") {
            toast(payload.text || "下载目录里有个文件处理不了", 5200);
          } else if (payload.kind === "extracted") {
            toast(`已自动解压 ${payload.name}`, 2600);
          } else if (payload.kind === "imported") {
            const n = payload.count || 0;
            toast(n ? `下载目录里发现 ${n} 个游戏，已自动导入` : "下载目录有更新", 3800);
            refreshLibrary().then(() => render()).catch(() => {});
          }
        }
      } catch (err) { console.error(err); }
    },
  };

  /* ---------------------------------------------------------- 启动 */
  async function boot() {
    // 逐个绑定并兜住异常：某一处出错也不至于让整个界面不响应
    for (const [name, fn] of [["窗口", bindWindowControls], ["背景", bindBgView], ["界面", bindUi]]) {
      try {
        fn();
      } catch (err) {
        console.error(name + "绑定失败", err);
        (window.__auroraErrors = window.__auroraErrors || []).push(`${name}绑定: ${err.message}`);
      }
    }
    if (missingIds.size) {
      const list = [...missingIds].join(", ");
      console.error("界面元素缺失:", list);
      (window.__auroraErrors = window.__auroraErrors || []).push("缺少界面元素: " + list);
      toast("界面元素缺失：" + list, 6000);
    }
    try {
      await refreshLibrary();
    } catch (e) {
      console.error(e);
      toast("初始化失败：" + e.message, 6000);
    }
    // 焦点：优先恢复上次看的那一款，否则用最近玩过的
    let want = null;
    try { want = localStorage.getItem("aurora.focus"); } catch (_) {}
    const has = (id) => id && state.games.some((g) => g.id === id);
    if (!has(want)) {
      const recent = state.games.slice().sort((a, b) => (b.last_played || 0) - (a.last_played || 0));
      want = recent[0]?.id || null;
    }
    state.focus = has(want) ? want : (state.games[0]?.id || ADD_KEY);
    render();
    scheduleBackground();
    el.boot.classList.add("done");
    setTimeout(() => el.boot.remove(), 600);

    setInterval(async () => {
      try {
        const res = await call("refresh_running");
        const running = new Set(res.running || []);
        let changed = false;
        state.games.forEach((g) => {
          const now = running.has(g.id);
          if (g.running !== now) { g.running = now; changed = true; }
        });
        if (changed) render();
      } catch (_) { /* ignore */ }
    }, 7000);
  }

  function bridgeReady() {
    const a = window.pywebview && window.pywebview.api;
    return !!(a && typeof a.bootstrap === "function");
  }

  function whenReady() {
    if (bridgeReady()) { pywebviewReady = true; boot(); return; }
    // pywebview 的 pywebviewready 事件可能早于函数注入，这里直接轮询到就绪
    let tries = 0;
    const timer = setInterval(() => {
      if (pywebviewReady) { clearInterval(timer); return; }
      if (bridgeReady()) {
        clearInterval(timer); pywebviewReady = true; boot();
      } else if (++tries > 300) {
        clearInterval(timer);
        el.boot.innerHTML =
          '<div style="text-align:center;color:#8b8b95;font-size:13px;line-height:1.7">' +
          "无法连接到本地服务，请重新启动 Aurora</div>";
      }
    }, 50);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", whenReady);
  } else {
    whenReady();
  }
})();
