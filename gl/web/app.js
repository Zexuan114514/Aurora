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
    categoriesView: $("categoriesView"), viewSwitch: $("viewSwitch"),
    catRoots: $("catRoots"), catShelves: $("catShelves"), catStatusList: $("catStatusList"),
    catDevs: $("catDevs"), catWall: $("catWall"), catBar: $("catBar"),
    catTitle: $("catTitle"), catSub: $("catSub"), catActions: $("catActions"),
    catCreate: $("catCreate"), catName: $("catName"), catHint: $("catHint"),
    catQuery: $("catQuery"), catSort: $("catSort"),
    scopePill: $("scopePill"), scopeLabel: $("scopeLabel"), scopeMenu: $("scopeMenu"),
    vntextPanel: $("vntextPanel"), vnThreads: $("vnThreads"), vnState: $("vnState"),
    vnHistory: $("vnHistory"), frameBox: $("frameBox"), frameImg: $("frameImg"),
    frameSel: $("frameSel"),
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
    view: "home",                                    // home | categories
    scope: { type: "all", value: "" },               // all | unfiled | shelf | status | dev
    shelves: [],
    shelfStats: { unfiled: 0, total: 0 },
    organizing: false,
    selected: new Set(),
    devExpand: false,
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

  /* 选择器里安全地写 id（游戏 id 是十六进制，理论上够用，仍然兜一层） */
  const cssEscape = (value) => (window.CSS && CSS.escape
    ? CSS.escape(String(value))
    : String(value).replace(/["\\]/g, "\\$&"));

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
    let list = state.games.filter(inScope);
    const q = state.filter.trim().toLowerCase();
    if (q) list = list.filter((g) => searchHit(g, q));
    return sortGames(list);
  }

  /* 搜索与排序：主页和分类工作区共用同一份逻辑，两处结果永远一致 */
  function searchHit(game, q) {
    return [game.name, game.steam_name, game.name_cn, game.name_original, game.exe_name,
            game.dir, (game.developers || []).join(" "), (game.publishers || []).join(" "),
            (game.genres || []).join(" "), (game.categories || []).join(" ")]
      .join(" ").toLowerCase().includes(q);
  }

  function sortGames(list) {
    if (state.sort === "favorite") {
      list.sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0));
    } else if (state.sort === "name") list.sort((a, b) => a.name.localeCompare(b.name, "zh"));
    else if (state.sort === "recent") list.sort((a, b) => (b.last_played || 0) - (a.last_played || 0));
    else if (state.sort === "playtime") list.sort((a, b) => (b.play_time || 0) - (a.play_time || 0));
    return list;
  }

  /* ---------------------------------------------------------- 作用域 */
  const STATUS_LABEL = { "": "未标记", playing: "在玩", cleared: "通关", shelved: "搁置" };
  const STATUS_GLYPH = { playing: "玩", cleared: "通", shelved: "搁" };
  const STATUS_ORDER = ["playing", "cleared", "shelved", ""];

  function inScope(game) {
    const scope = state.scope;
    if (scope.type === "shelf") return (game.bookshelf_ids || []).includes(scope.value);
    if (scope.type === "unfiled") return !(game.bookshelf_ids || []).length;
    if (scope.type === "fav") return !!game.favorite;
    if (scope.type === "status") return (game.status || "") === scope.value;
    if (scope.type === "dev") return (game.developers || []).includes(scope.value);
    return true;
  }

  function scopeName(scope = state.scope) {
    if (scope.type === "shelf") {
      const shelf = state.shelves.find((s) => s.id === scope.value);
      return shelf ? shelf.name : "分类";
    }
    if (scope.type === "unfiled") return "未分类";
    if (scope.type === "fav") return "已收藏";
    if (scope.type === "status") return STATUS_LABEL[scope.value] ?? "状态";
    if (scope.type === "dev") return scope.value;
    return "全部游戏";
  }

  const scopeCount = () => state.games.filter(inScope).length;

  function syncScopePill() {
    const active = state.scope.type !== "all";
    el.scopeLabel.textContent = `${scopeName()} · ${scopeCount()}`;
    $("scopeClear").hidden = !active;
  }

  function setScope(type, value = "") {
    state.scope = type && type !== "all" ? { type, value: value || "" } : { type: "all", value: "" };
    state.selected.clear();
    try { localStorage.setItem("aurora.scope", JSON.stringify(state.scope)); } catch (_) { /* ignore */ }
    // 焦点跟着作用域走：切分类时落到该分类的第一款，空分类就落在「＋」上
    const games = visibleGames();
    if (!games.some((g) => g.id === state.focus)) state.focus = games[0]?.id || ADD_KEY;
    render();
    if (state.view === "home") updateRow();
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
    if (game.status && STATUS_GLYPH[game.status]) {
      badges.push(`<span class="gi-badge st-${esc(game.status)}" title="${
        esc(STATUS_LABEL[game.status])}">${STATUS_GLYPH[game.status]}</span>`);
    }
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
    document.body.classList.toggle("settings-open", state.settingsOpen);
    $("btnSettings").classList.toggle("on", state.settingsOpen);
    for (const btn of el.viewSwitch.querySelectorAll(".vs-btn")) {
      btn.classList.toggle("on", btn.dataset.view === state.view);
      btn.disabled = state.settingsOpen;
    }
    syncScopePill();
    // 视图可见性只在这里决定：设置 / 分类 / 游戏页 / 大厅，互斥且一定会恢复
    const showSettings = state.settingsOpen;
    const showCategories = !showSettings && state.view === "categories";
    el.settingsView.hidden = !showSettings;
    el.categoriesView.hidden = !showCategories;
    if (showSettings || showCategories) {
      el.hall.hidden = true;
      el.view.hidden = true;
      el.empty.hidden = true;
      if (showCategories) renderCategories();
      return;
    }
    // 回到主页：按 page 决定显示大厅还是游戏页（进来时可能被上面藏过）
    if (state.page === "game" && currentGame()) {
      el.view.hidden = false;
      el.hall.hidden = true;
    } else {
      el.view.hidden = true;
    }
  }

  /* ---------------------------------------------------------- 分类工作区 */
  const DEV_LIMIT = 12;

  function setView(name) {
    const next = name === "categories" ? "categories" : "home";
    state.view = next;
    state.organizing = false;
    state.selected.clear();
    if (state.settingsOpen) state.settingsOpen = false;
    closeAll();
    render();
    if (next === "home") updateRow();
  }

  function catList() {
    let list = state.games.filter(inScope);
    const q = state.filter.trim().toLowerCase();
    if (q) list = list.filter((g) => searchHit(g, q));
    return sortGames(list);
  }

  function catItem(active, attrs, label, count, ops = "") {
    return `<button class="cat-item${active ? " on" : ""}" ${attrs}>
      <span>${esc(label)}</span>
      <small>${count}</small>${ops}</button>`;
  }

  function renderCatRoots() {
    const total = state.shelfStats.total ?? state.games.length;
    const unfiled = state.shelfStats.unfiled ?? 0;
    const favorite = state.games.filter((g) => g.favorite).length;
    el.catRoots.innerHTML =
      catItem(state.scope.type === "all", 'data-scope="all"', "全部游戏", total)
      + catItem(state.scope.type === "unfiled", 'data-scope="unfiled"', "未分类", unfiled)
      + catItem(state.scope.type === "fav", 'data-scope="fav"', "已收藏", favorite);
  }

  function renderCatShelves() {
    if (!state.shelves.length) {
      el.catShelves.innerHTML =
        '<p class="cat-hint" style="color:var(--text-3)">还没有分类，点右上角 ＋ 新建一个。</p>';
      return;
    }
    el.catShelves.innerHTML = state.shelves.map((shelf, index) => {
      const active = state.scope.type === "shelf" && state.scope.value === shelf.id;
      // 注意：按钮不能嵌套按钮（浏览器会把内层摊平），所以外面再包一层行容器
      return `<div class="cat-row${active ? " on" : ""}">
        <button class="cat-item${active ? " on" : ""}" data-scope="shelf"
                data-id="${esc(shelf.id)}">
          <span>${esc(shelf.name)}</span><small>${shelf.count ?? 0}</small>
        </button>
        <span class="cat-ops">
          <button data-shelf-move="${esc(shelf.id)}" data-delta="-1" title="上移"${
            index === 0 ? " disabled" : ""}>↑</button>
          <button data-shelf-move="${esc(shelf.id)}" data-delta="1" title="下移"${
            index === state.shelves.length - 1 ? " disabled" : ""}>↓</button>
          <button data-shelf-rename="${esc(shelf.id)}" title="重命名">✎</button>
          <button class="danger" data-shelf-del="${esc(shelf.id)}" title="删除分类">✕</button>
        </span>
      </div>`;
    }).join("");
  }

  function renderCatStatus() {
    el.catStatusList.innerHTML = STATUS_ORDER.map((value) => {
      const count = state.games.filter((g) => (g.status || "") === value).length;
      const active = state.scope.type === "status" && state.scope.value === value;
      return catItem(active, `data-scope="status" data-id="${esc(value)}"`,
                     STATUS_LABEL[value], count);
    }).join("");
  }

  function renderCatDevs() {
    const counts = new Map();
    for (const game of state.games) {
      for (const dev of (game.developers || [])) {
        if (dev) counts.set(dev, (counts.get(dev) || 0) + 1);
      }
    }
    const rows = [...counts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh"));
    const shown = state.devExpand ? rows : rows.slice(0, DEV_LIMIT);
    el.catDevs.innerHTML = shown.map(([name, count]) => catItem(
      state.scope.type === "dev" && state.scope.value === name,
      `data-scope="dev" data-id="${esc(name)}"`, name, count)).join("")
      + (rows.length > DEV_LIMIT
          ? `<button class="cat-item" data-dev-more="1"><span>${
              state.devExpand ? "收起" : `更多（${rows.length - DEV_LIMIT}）`}</span></button>`
          : "");
  }

  function renderCatHead() {
    const list = catList();
    el.catTitle.textContent = scopeName();
    el.catSub.textContent = `${list.length} 部`
      + (state.filter.trim() ? `（筛选自 ${scopeCount()} 部）` : "");
    const shelf = state.scope.type === "shelf"
      ? state.shelves.find((s) => s.id === state.scope.value) : null;
    const actions = [];
    if (state.organizing) {
      actions.push('<button class="mini-btn on" data-cat="organize">完成整理</button>');
    } else {
      actions.push('<button class="mini-btn" data-cat="organize">批量归类</button>');
      if (shelf) {
        actions.push('<button class="mini-btn" data-cat="rename">重命名</button>');
        actions.push('<button class="mini-btn" data-cat="delete">删除分类</button>');
      }
    }
    el.catActions.innerHTML = actions.join("");
  }

  function renderCatWall() {
    const list = catList();
    if (!list.length) {
      el.catWall.innerHTML = `<div class="cat-empty">${
        state.filter.trim() ? "这个范围里没有匹配的游戏。" : "这个范围里还没有游戏。"}</div>`;
      return;
    }
    el.catWall.innerHTML = list.map((game) => {
      const picked = state.selected.has(game.id);
      const sub = (game.developers || [])[0] || STATUS_LABEL[game.status || ""] || "";
      return `<button class="cat-card${picked ? " on" : ""}" data-id="${esc(game.id)}"
                      title="${esc(game.name)}">
        <span class="cat-art">${imgHtml("", coverSources(game))}
          <b>${esc((game.name || "?").trim().charAt(0).toUpperCase())}</b>
          ${state.organizing ? `<i class="cat-mark">${picked ? "✓" : ""}</i>` : ""}
        </span>
        <span class="cat-name">${esc(game.name)}</span>
        <span class="cat-dev">${esc(sub)}</span>
      </button>`;
    }).join("");
  }

  function renderCatBar() {
    if (!state.organizing) {
      el.catBar.hidden = true;
      el.catBar.innerHTML = "";
      return;
    }
    const inShelf = state.scope.type === "shelf" ? state.scope.value : "";
    el.catBar.hidden = false;
    el.catBar.innerHTML = `
      <b>已选 ${state.selected.size} 部</b>
      <button class="mini-btn" data-catbar="all">全选当前结果</button>
      <button class="mini-btn" data-catbar="none">清空</button>
      <select id="catTarget"><option value="">选择目标分类</option>${
        state.shelves.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}
      </select>
      <button class="mini-btn" data-catbar="add">加入分类</button>
      ${inShelf ? '<button class="mini-btn" data-catbar="remove">移出当前分类</button>' : ""}
      <button class="mini-btn" data-catbar="fav">收藏</button>
      <button class="mini-btn" data-catbar="unfav">取消收藏</button>
      <span class="hint">点封面勾选</span>`;
  }

  function renderCategories() {
    renderCatRoots();
    renderCatShelves();
    renderCatStatus();
    renderCatDevs();
    renderCatHead();
    renderCatWall();
    renderCatBar();
    if (el.catQuery.value !== state.filter) el.catQuery.value = state.filter;
    if (el.catSort.value !== state.sort) el.catSort.value = state.sort;
  }

  /* 分类接口统一收尾：合并货架列表与受影响的游戏 */
  function applyShelfPayload(res) {
    if (!res) return;
    if (Array.isArray(res.shelves)) state.shelves = res.shelves;
    if (typeof res.unfiled === "number") {
      state.shelfStats = { unfiled: res.unfiled, total: res.total ?? state.games.length };
    }
    if (Array.isArray(res.games)) {
      for (const row of res.games) {
        const index = state.games.findIndex((g) => g.id === row.id);
        if (index >= 0) state.games[index] = { ...state.games[index], ...row };
      }
    }
    if (res.removed) {
      for (const game of state.games) {
        game.bookshelf_ids = (game.bookshelf_ids || []).filter((x) => x !== res.removed);
      }
    }
    render();
  }

  async function refreshShelves() {
    try {
      applyShelfPayload(await call("list_shelves"));
    } catch (_) { /* 离线时保留现有状态 */ }
  }

  /* 主页作用域菜单：不用进分类界面也能直接选一个范围 */
  function scopeRow(type, value, label, count) {
    const on = state.scope.type === type && (state.scope.value || "") === (value || "");
    return `<button class="${on ? "on" : ""}" data-scope-type="${esc(type)}"
                    data-scope-value="${esc(value || "")}">
      <span>${esc(label)}</span><small>${count}</small></button>`;
  }

  function renderScopeMenu() {
    const rows = [];
    rows.push(`<div class="scope-group">范围</div>`);
    rows.push(scopeRow("all", "", "全部游戏", state.games.length));
    rows.push(scopeRow("unfiled", "", "未分类",
                       state.shelfStats.unfiled ?? state.games.filter(
                         (g) => !(g.bookshelf_ids || []).length).length));
    rows.push(scopeRow("fav", "", "已收藏",
                       state.games.filter((g) => g.favorite).length));
    if (state.shelves.length) {
      rows.push(`<div class="scope-group">自定义分类</div>`);
      for (const shelf of state.shelves) {
        rows.push(scopeRow("shelf", shelf.id, shelf.name, shelf.count ?? 0));
      }
    }
    rows.push(`<div class="scope-group">按状态</div>`);
    for (const value of STATUS_ORDER) {
      const count = state.games.filter((g) => (g.status || "") === value).length;
      rows.push(scopeRow("status", value, STATUS_LABEL[value], count));
    }
    const devs = new Map();
    for (const game of state.games) {
      for (const dev of (game.developers || [])) {
        if (dev) devs.set(dev, (devs.get(dev) || 0) + 1);
      }
    }
    if (devs.size) {
      rows.push(`<div class="scope-group">按开发商</div>`);
      for (const [name, count] of [...devs.entries()]
          .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh")).slice(0, 12)) {
        rows.push(scopeRow("dev", name, name, count));
      }
    }
    el.scopeMenu.innerHTML = rows.join("");
  }

  function openScopeMenu() {
    renderScopeMenu();
    el.scopeMenu.hidden = false;
    const rect = el.scopePill.getBoundingClientRect();
    const box = el.scopeMenu.getBoundingClientRect();
    let left = Math.round(rect.left);
    left = Math.max(12, Math.min(window.innerWidth - box.width - 12, left));
    let top = Math.round(rect.bottom + 8);
    if (top + box.height > window.innerHeight - 12) {
      top = Math.max(80, Math.round(rect.top - box.height - 8));
    }
    el.scopeMenu.style.left = left + "px";
    el.scopeMenu.style.top = top + "px";
  }

  function setOrganizing(on) {
    state.organizing = !!on;
    if (!state.organizing) state.selected.clear();
    render();
  }

  function togglePick(gameId) {
    if (state.selected.has(gameId)) state.selected.delete(gameId);
    else state.selected.add(gameId);
    // 只改这一张卡片的勾选态：整墙重绘会让连点丢事件、也会闪
    const card = el.catWall.querySelector(`.cat-card[data-id="${cssEscape(gameId)}"]`);
    if (card) {
      const on = state.selected.has(gameId);
      card.classList.toggle("on", on);
      const mark = card.querySelector(".cat-mark");
      if (mark) mark.textContent = on ? "✓" : "";
    }
    renderCatBar();
  }

  async function createShelf(name) {
    const res = await call("create_shelf", name);
    if (!res || !res.ok) {
      el.catHint.textContent = res && res.error === "duplicate" ? "已经有同名的分类了"
        : (res && res.error === "too-long" ? "名字太长了（最多 24 字）" : "名字不能为空");
      return null;
    }
    el.catHint.textContent = "";
    el.catCreate.hidden = true;
    el.catName.value = "";
    applyShelfPayload(res);
    toast(`已新建分类「${res.shelf.name}」`);
    return res.shelf;
  }

  async function renameShelfFlow(id) {
    const shelf = state.shelves.find((s) => s.id === id);
    if (!shelf) return;
    const value = await modal({
      title: "重命名分类", body: "只改分类名字，不动里面的游戏。",
      input: true, value: shelf.name, okText: "保存",
    });
    if (value === null) return;
    const res = await call("rename_shelf", id, value);
    if (!res || !res.ok) {
      toast(res && res.error === "duplicate" ? "已经有同名的分类了" : "名字不能为空");
      return;
    }
    applyShelfPayload(res);
    toast("已重命名分类");
  }

  async function deleteShelfFlow(id) {
    const shelf = state.shelves.find((s) => s.id === id);
    if (!shelf) return;
    const ok = await modal({
      title: "删除分类",
      body: `删除「${shelf.name}」？游戏和游玩记录都不会动，只是不再归在这个分类里。`,
      okText: "删除",
    });
    if (!ok) return;
    applyShelfPayload(await call("delete_shelf", id));
    if (state.scope.type === "shelf" && state.scope.value === id) setScope("all");
    toast("已删除分类");
  }

  async function assignSelected(target) {
    const ids = [...state.selected];
    if (!ids.length) { toast("先勾选几张封面"); return; }
    if (!target) { toast("先在下拉里选一个目标分类"); return; }
    const res = await call("add_games_to_shelf", ids, [target]);
    state.selected.clear();
    applyShelfPayload(res);
    const shelf = state.shelves.find((s) => s.id === target);
    toast(`已把 ${res.count || 0} 部加入「${shelf ? shelf.name : "分类"}」`);
  }

  async function removeSelectedFromScope() {
    const ids = [...state.selected];
    if (state.scope.type !== "shelf" || !ids.length) return;
    const res = await call("remove_games_from_shelf", ids, state.scope.value);
    state.selected.clear();
    applyShelfPayload(res);
    toast(`已移出 ${res.count || 0} 部`);
  }

  async function favoriteSelected(value) {
    const ids = [...state.selected];
    if (!ids.length) { toast("先勾选几张封面"); return; }
    const res = await call("set_games_favorite", ids, value);
    toast(value ? `已收藏 ${res.count || 0} 部` : `已取消收藏 ${res.count || 0} 部`);
    applyShelfPayload(res);
  }

  async function setGameStatus(gameId, status) {
    const res = await call("set_game_status", gameId, status);
    if (!res || !res.ok) { toast("保存状态失败"); return; }
    const game = state.games.find((g) => g.id === gameId);
    if (game && res.game) Object.assign(game, res.game);
    render();
    renderDetail();
    toast(status ? `已标记为「${STATUS_LABEL[status]}」` : "已清除状态标记");
  }

  /* ---------------------------------------------------------- 游戏内翻译 */
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

  const vnErrorText = (state) => {
    const error = (state && state.error) || "";
    return VN_ERROR_LABEL[error] || error;
  };

  function renderVntextPanel(state) {
    if (!state) return;
    const running = !!state.running;
    $("vnToggle").firstElementChild.textContent = running ? "停止翻译" : "开启翻译";
    $("vnPause").firstElementChild.textContent = state.paused ? "继续" : "暂停";
    const parts = [running ? `正在翻译（${VN_ENGINE_LABEL[state.engine || ""] || state.engine}）`
                           : "未开启"];
    if (running && state.pid) parts.push(`PID ${state.pid}`);
    parts.push(`已译 ${state.lines || 0} 句`);
    if (running && !state.llm_ready) parts.push("没配 LLM Key：正在用免费接口，质量与速度较差");
    if (state.engine_name && state.engine_name !== "unknown") {
      parts.push(`引擎：${state.engine_name}`);
    }
    if (state.merged) parts.push(`已合并 ${state.merged} 份重复文本`);
    if (state.hook_hint) parts.push(state.hook_hint);
    if (running && state.engine === "hook" && state.game_locale === false) {
      parts.push("这个游戏没开转区：日文原版很容易出乱码，建议用「⋯ → 转区启动…」开启后再翻译");
    }
    const hk = state.hotkeys || {};
    if (running && hk.registered && hk.registered.length) {
      parts.push("Ctrl+Alt+T 切换穿透");
    } else if (running) {
      parts.push("全局热键没注册成功（可能被别的软件占用），请点下面的「切换穿透」");
    }
    const error = vnErrorText(state);
    let detail = error;
    if (state.error === "wrong-bitness") {
      detail = `这个游戏是 ${state.target_bits || "?"} 位，当前的 TextractorCLI 是 ${
        state.cli_bits || "?"} 位；请在 设置 → 游戏内翻译 里换成 ${
        state.target_bits === 32 ? "x86" : "x64"} 版`;
    }
    el.vnState.textContent = parts.join(" · ") + (detail ? ` · ${detail}` : "");

    const locked = state.locked || "";
    el.vnThreads.innerHTML = (state.threads || []).map((row) => `
      <button class="vn-thread${row.key === locked ? " on" : ""}" data-vn-thread="${esc(row.key)}"
              title="${esc(row.sample || "")}">
        <span>${esc(row.name || row.key)}</span><small>${row.count}</small>
      </button>`).join("");

    const region = state.region || {};
    $("vnRegion").textContent = `x${Math.round((region.x || 0) * 100)}% y${
      Math.round((region.y || 0) * 100)}% · ${Math.round((region.w || 1) * 100)}%×${
      Math.round((region.h || 0.34) * 100)}%`;

    const history = state.history || [];
    el.vnHistory.innerHTML = history.slice(-6).reverse().map((row) => `
      <div class="vn-row"><i>${esc(row.text)}</i>${esc(row.translation)}</div>`).join("")
      || '<div class="vn-row"><i>还没有译文</i>开启翻译后，游戏里的日文会实时出现在这里和悬浮窗上。</div>';
  }

  function renderVntextSettings(state) {
    const tractor = state.tractor || {};
    $("setVnPath").value = tractor.path || tractor.saved || "";
    $("setVnContext").value = state.context_lines ?? 4;
    $("setVnContextVal").textContent = (state.context_lines ?? 4) + " 句";
    $("setVnAuto").checked = !!state.auto_start;
    const overlay = state.overlay || {};
    const font = overlay.font || 20;
    const opacity = Math.round((overlay.opacity ?? 0.9) * 100);
    $("setVnFont").value = font;
    $("setVnFontVal").textContent = font + "px";
    $("setVnOpacity").value = opacity;
    $("setVnOpacityVal").textContent = opacity + "%";
    const ocrInfo = state.ocr || {};
    $("setVnOcr").textContent = ocrInfo.lang_ready
      ? "日语 OCR 组件已就绪，可以只用 OCR 模式。"
      : `系统还没装「日语 OCR」组件（当前可用：${(ocrInfo.languages || []).join(" / ") || "无"}）。`
        + "点「安装日语 OCR 组件…」按提示添加日语并勾选光学字符识别。";
    $("vnStatus").textContent = tractor.found
      ? `TextractorCLI：${tractor.path}`
      : "没有检测到 TextractorCLI。装好 Textractor 后点「重新检测」，或手动指定；只用 OCR 也可以。";
    const builds = state.builds || [];
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

  async function refreshVntext() {
    let state = null;
    try {
      state = await call("get_vntext_status");
    } catch (_) { /* 离线时保留原样 */ }
    if (state) {
      renderVntextPanel(state);
      renderVntextSettings(state);
    }
    return state;
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
    if (!res || !res.ok) { toast("术语表更新失败"); return; }
    await renderGlossary();
    toast(dst ? "已加入术语表" : "已删除术语");
  }

  function openVntextPanel() {
    closeAll();
    openPanel(el.vntextPanel);
    refreshVntext();
  }

  /* OCR 区域框选：先截一张游戏窗口图，再在上面拖框 */
  let frameRect = null;

  async function openFraming() {
    const gameId = state.focus;
    if (!gameId || gameId === ADD_KEY) return;
    const res = await call("capture_game_frame", gameId);
    if (!res || !res.ok) {
      toast("截图失败：" + (vnErrorText({ error: (res && res.error) || "" }) || "未知原因"), 4200);
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
      if (!frameRect || frameRect.width < 8 || frameRect.height < 8) { toast("先拖一个框"); return; }
      const region = {
        x: frameRect.left / rect.width,
        y: frameRect.top / rect.height,
        w: frameRect.width / rect.width,
        h: frameRect.height / rect.height,
      };
      await call("set_vntext_region", gameId, region);
      el.frameBox.hidden = true;
      frameRect = null;
      toast("已记住这个游戏的 OCR 区域");
      refreshVntext();
    };
  }

  function bindVntext() {
    $("btnVntext").onclick = openVntextPanel;
    $("vnClose").onclick = () => closePanel(el.vntextPanel);
    $("vnToggle").onclick = async () => {
      const status = await call("get_vntext_status");
      if (status && status.running) {
        await call("stop_vntext");
        toast("已停止翻译");
      } else {
        const res = await call("start_vntext", state.focus);
        toast(res && res.ok ? "翻译已开启，悬浮窗会显示译文"
                            : "开启失败：" + (vnErrorText(res || {}) || "未知原因"), 5200);
      }
      refreshVntext();
    };
    $("vnPush").onclick = async () => {
      const res = await call("toggle_overlay");
      toast(res && res.visible ? "悬浮窗已显示" : "悬浮窗已隐藏");
    };
    $("vnRetry").onclick = async () => {
      const last = el.vnHistory.querySelector("i");
      const res = await call("translate_line_now", last ? last.textContent : "");
      toast(res && res.ok ? "正在重译…" : "还没有可重译的台词");
    };
    $("vnThrough").onclick = async () => {
      const status = await call("get_vntext_status");
      const on = !(status && status.overlay && status.overlay.click_through === false);
      const res = await call("set_overlay_click_through", on);
      toast(on ? "悬浮窗已设为鼠标穿透"
               : "悬浮窗已可点击：拖标题栏移动，拖右下角或任意边缘缩放");
      refreshVntext();
    };
    $("vnPause").onclick = async () => {
      const status = await call("get_vntext_status");
      const res = await call("set_vntext_paused", !(status && status.paused));
      toast(res && res.paused ? "已暂停翻译" : "已继续翻译");
      refreshVntext();
    };
    $("vnHookSend").onclick = async () => {
      const code = $("vnHook").value.trim();
      if (!code) { toast("先粘贴 hook 码"); return; }
      const res = await call("send_hook_code", code);
      toast(res && res.ok ? "已发送 hook 码" : "发送失败（当前不是钩子模式）");
      refreshVntext();
    };
    el.vnThreads.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-vn-thread]");
      if (!btn) return;
      const key = btn.dataset.vnThread;
      const current = btn.classList.contains("on");
      await call("lock_vntext_thread", current ? "" : key);
      toast(current ? "已取消锁定线程" : "已锁定这个线程");
      refreshVntext();
    });
    $("vnFraming").onclick = openFraming;
    bindFraming();

    $("setVnEngine").onchange = async (e) => {
      state.settings.vntext_engine = e.target.value;
      await call("set_vntext_option", "vntext_engine", e.target.value);
      toast("已切换翻译引擎");
      refreshVntext();
    };
    $("setVnPick").onclick = async () => {
      const res = await call("pick_textractor");
      if (!res || res.cancelled) return;
      if (!res.ok) { toast("这个路径不可用"); return; }
      toast("已指定 TextractorCLI");
      refreshVntext();
    };
    $("setVnBuilds").addEventListener("click", async (e) => {
      const chip = e.target.closest("[data-vn-build]");
      if (!chip) return;
      const res = await call("set_vntext_option", "vntext_tractor_path", chip.dataset.vnBuild);
      if (!res || !res.ok) { toast("这个路径不可用"); return; }
      toast("已切换 TextractorCLI");
      refreshVntext();
    });
    $("setVnDownload").onclick = () => call("open_textractor_page");
    $("setVnRefresh").onclick = () => { refreshVntext(); toast("已重新检测"); };
    $("setVnLang").onclick = () => call("open_language_settings");
    $("setVnContext").oninput = (e) => { $("setVnContextVal").textContent = e.target.value + " 句"; };
    $("setVnContext").onchange = (e) =>
      call("set_vntext_option", "vntext_context_lines", Number(e.target.value));
    $("setVnAuto").onchange = async (e) => {
      await call("set_vntext_option", "vntext_auto_start", e.target.checked);
      toast(e.target.checked ? "启动游戏时会自动开始翻译" : "已关闭自动翻译");
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
      if (!src || !dst) { toast("日文和中文都要填"); return; }
      setGlossary(src, dst, $("glossaryGame").checked ? state.focus : "");
      $("glossarySrc").value = "";
      $("glossaryDst").value = "";
    };
    $("glossaryList").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-glossary-del]");
      if (btn) setGlossary(btn.dataset.glossaryDel, "", btn.dataset.scope || "");
    });
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
    refreshVntext();
    renderGlossary();
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
      ["状态", `<select id="detailStatus" data-id="${esc(g.id)}">${
        STATUS_ORDER.map((value) => `<option value="${esc(value)}"${
          (g.status || "") === value ? " selected" : ""}>${STATUS_LABEL[value]}</option>`).join("")
      }</select>`],
      ["分类", (g.bookshelf_ids || [])
        .map((id) => (state.shelves.find((s) => s.id === id) || {}).name)
        .filter(Boolean)
        .map((name) => `<span class="src-badge">${esc(name)}</span>`)
        .join(" ")],
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
    closePanel(el.vntextPanel);
    closePanel(el.getPanel);
    el.moreMenu.hidden = true;
    el.sortMenu.hidden = true;
    el.addMenu.hidden = true;
    el.scopeMenu.hidden = true;
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
    await refreshShelves();
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

  /* ---------------------------------------------------------- 主题与配色 */
  const PALETTES = [
    { key: "aurora", name: "极光蓝", accent: "#0A84FF", accent2: "#4FA9FF" },
    { key: "lime", name: "薄荷青", accent: "#26C6A8", accent2: "#6FE0C8" },
    { key: "sakura", name: "樱花粉", accent: "#FF5C8A", accent2: "#FF9AB6" },
    { key: "amber", name: "琥珀橙", accent: "#FF9F0A", accent2: "#FFC46B" },
  ];
  const lightQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

  function effectiveTheme() {
    const mode = state.settings.theme_mode || "dark";
    if (mode === "auto") return lightQuery && lightQuery.matches ? "light" : "dark";
    return mode === "light" ? "light" : "dark";
  }

  /* 主题只负责 data-theme / data-palette 与窗口外框；强调色跟着设置走 */
  function applyTheme() {
    const theme = effectiveTheme();
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.palette = state.settings.palette || "aurora";
    try { call("apply_window_theme", theme === "light").catch(() => {}); } catch (_) { /* 离线 */ }
  }

  function renderPaletteRow() {
    const active = state.settings.palette || "aurora";
    $("setPalettes").innerHTML = PALETTES.map((p) => `
      <button type="button" class="palette-chip${active === p.key ? " on" : ""}"
              data-palette="${p.key}" title="${p.name}">
        <i style="background:${p.accent}"></i><span>${p.name}</span>
      </button>`).join("")
      + `<span class="palette-custom${active === "custom" ? " on" : ""}">自定义</span>`;
  }

  function bindTheme() {
    $("setTheme").onchange = async (e) => {
      await saveSetting("theme_mode", e.target.value);
      applyTheme();
      toast(e.target.value === "light" ? "已切换到浅色主题"
        : (e.target.value === "auto" ? "主题跟随系统" : "已切换到深色主题"));
    };
    $("setPalettes").onclick = async (e) => {
      const chip = e.target.closest("[data-palette]");
      if (!chip) return;
      const preset = PALETTES.find((p) => p.key === chip.dataset.palette);
      if (!preset) return;
      state.settings.palette = preset.key;
      state.settings.accent = preset.accent;
      applySettingsToUi();
      renderPaletteRow();
      await call("set_setting", "palette", preset.key);
      await call("set_setting", "accent", preset.accent);
      toast(`已应用配色：${preset.name}`);
    };
    if (lightQuery) {
      const onChange = () => { if ((state.settings.theme_mode || "dark") === "auto") applyTheme(); };
      if (lightQuery.addEventListener) lightQuery.addEventListener("change", onChange);
      else if (lightQuery.addListener) lightQuery.addListener(onChange);
    }
  }

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
    applyTheme();

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
    $("setTheme").value = s.theme_mode || "dark";
    renderPaletteRow();
    $("setVnEngine").value = s.vntext_engine || "auto";
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

    /* 鼠标在窗口外松开、或窗口切走时收不到 mouseup，状态必须主动清掉，
       否则会出现「没按键也在拖窗口 / 划封面」这种鬼畜行为 */
    function dropPointerState() {
      if (drag) { drag = null; call("drag_end"); }
      if (resize) { resize = null; }
      if (swipe) swipe = null;
    }
    document.addEventListener("mouseup", dropPointerState);
    window.addEventListener("blur", dropPointerState);
    document.addEventListener("mouseleave", dropPointerState);

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
      // 设置页 / 分类工作区里滚轮只滚动各自的内容
      if (state.settingsOpen || state.view === "categories") return;
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
        if (state.settingsOpen || state.view === "categories") return;
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
      if (!tile || tile.dataset.add || moved) return;
      setFocus(tile.dataset.id);
      openGame(tile.dataset.id);
      togglePlay();
    });

    // 横向拖动 = 换一张封面
    const swipeStart = (e) => {
      if (e.button !== 0) return;
      // 关键：每次左键按下都先复位「这次是拖拽还是单击」。
      // 不复位的话，拖过一次之后 moved 永远为 true，之后所有单击都会被当成拖拽丢掉。
      moved = false;
      if (state.settingsOpen || state.view === "categories") return;
      // 工具条 / 底部信息带是拖窗口的区域，别在这里抢滑动
      if (e.target.closest("button, a, input, .pill, [data-drag], .rz")) return;
      swipe = { x: e.clientX, y: e.clientY, base: e.clientX };
    };
    const swipeMove = (e) => {
      if (!swipe || state.settingsOpen || state.view === "categories") return;
      const dx = e.clientX - swipe.base;
      const dy = e.clientY - swipe.y;
      if (Math.abs(dx) < 64 || Math.abs(dy) > Math.abs(dx)) return;
      moved = true;
      swipe.base = e.clientX;
      moveFocus(dx < 0 ? 1 : -1);
    };
    // 捕获阶段：保证在任何其它 mousedown 处理（窗口拖拽等）之前先把状态复位
    $("app").addEventListener("mousedown", swipeStart, true);
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
    // 齿轮是开关：点开、再点一次（或用「← 返回」）都能退出设置
    $("btnSettings").onclick = () => (state.settingsOpen ? closeSettings() : openSettings());
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
    $("setAccent").onchange = async (e) => {
      await saveSetting("accent", e.target.value);
      await saveSetting("palette", "custom");     // 手选颜色 = 自定义配色
      renderPaletteRow();
    };
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

    // 视图切换：主页 / 分类
    el.viewSwitch.addEventListener("click", (e) => {
      const btn = e.target.closest(".vs-btn");
      if (!btn || btn.disabled) return;
      if (btn.dataset.view === "categories") {
        setView("categories");
        refreshShelves();
      } else {
        setView("home");
      }
    });
    $("scopePick").onclick = () => {
      const wasHidden = el.scopeMenu.hidden;
      closeAll();
      if (wasHidden) openScopeMenu();
    };
    $("scopeClear").onclick = () => {
      el.scopeMenu.hidden = true;
      setScope("all");
      toast("已显示全部游戏");
    };
    el.scopeMenu.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-scope-type]");
      if (!btn) return;
      el.scopeMenu.hidden = true;
      setScope(btn.dataset.scopeType, btn.dataset.scopeValue || "");
    });

    // 分类工作区（事件委托，界面重绘后依然有效）
    el.categoriesView.addEventListener("click", async (e) => {
      const scopeBtn = e.target.closest("[data-scope]");
      if (scopeBtn) {
        setScope(scopeBtn.dataset.scope, scopeBtn.dataset.id || "");
        return;
      }
      if (e.target.closest("[data-dev-more]")) {
        state.devExpand = !state.devExpand;
        renderCatDevs();
        return;
      }
      const move = e.target.closest("[data-shelf-move]");
      if (move && !move.disabled) {
        await moveShelf(move.dataset.shelfMove, Number(move.dataset.delta));
        return;
      }
      const ren = e.target.closest("[data-shelf-rename]");
      if (ren) { await renameShelfFlow(ren.dataset.shelfRename); return; }
      const del = e.target.closest("[data-shelf-del]");
      if (del) { await deleteShelfFlow(del.dataset.shelfDel); return; }
      const act = e.target.closest("[data-cat]");
      if (act) {
        if (act.dataset.cat === "organize") setOrganizing(!state.organizing);
        else if (act.dataset.cat === "rename") renameShelfFlow(state.scope.value);
        else if (act.dataset.cat === "delete") deleteShelfFlow(state.scope.value);
        return;
      }
      const bar = e.target.closest("[data-catbar]");
      if (bar) {
        const kind = bar.dataset.catbar;
        if (kind === "all") {
          state.selected = new Set(catList().map((g) => g.id));
          renderCatWall();
          renderCatBar();
        } else if (kind === "none") {
          state.selected.clear();
          renderCatWall();
          renderCatBar();
        } else if (kind === "add") {
          const target = $("catTarget");
          assignSelected(target ? target.value : "");
        } else if (kind === "remove") removeSelectedFromScope();
        else if (kind === "fav") favoriteSelected(true);
        else if (kind === "unfav") favoriteSelected(false);
        return;
      }
      const card = e.target.closest(".cat-card");
      if (card) {
        const id = card.dataset.id;
        if (state.organizing) {
          togglePick(id);
        } else {
          setFocus(id);
          renderDetail();
          openPanel(el.detailPanel);
        }
      }
    });

    $("catNew").onclick = () => {
      el.catCreate.hidden = false;
      el.catHint.textContent = "";
      el.catName.focus();
    };
    $("catCancel").onclick = () => {
      el.catCreate.hidden = true;
      el.catHint.textContent = "";
    };
    el.catCreate.addEventListener("submit", async (e) => {
      e.preventDefault();
      const shelf = await createShelf(el.catName.value.trim());
      if (shelf) setScope("shelf", shelf.id);
    });

    // 分类工作区与主页共用同一份搜索 / 排序
    el.catQuery.addEventListener("input", (e) => {
      state.filter = e.target.value;
      el.search.value = state.filter;
      el.searchClear.hidden = !state.filter;
      renderHall();
      renderCatHead();
      renderCatWall();
    });
    el.catSort.onchange = (e) => {
      state.sort = e.target.value;
      syncSortMenu();
      renderHall();
      renderCatHead();
      renderCatWall();
    };
    el.detailBody.addEventListener("change", (e) => {
      if (e.target.id === "detailStatus") setGameStatus(e.target.dataset.id, e.target.value);
    });
    bindTheme();
    bindVntext();

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
      if (el.catQuery.value !== state.filter) el.catQuery.value = state.filter;   // 两处搜索同步
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
      if (!e.target.closest("#scopeMenu, #scopePill")) el.scopeMenu.hidden = true;
    });
    document.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || e.target?.isContentEditable;
      if (e.key === "Escape") {
        const anyOpen = [el.bgPanel, el.detailPanel, el.matchPanel, el.sourcePanel,
                         el.coverPanel, el.steamPanel, el.localePanel, el.vntextPanel,
                         el.getPanel]
          .some((p) => p.classList.contains("open"));
        const menuOpen = !el.moreMenu.hidden || !el.sortMenu.hidden || !el.addMenu.hidden
          || !el.scopeMenu.hidden;
        if (anyOpen || menuOpen) { closeAll(); return; }
        if (state.settingsOpen) { closeSettings(); return; }
        if (state.view === "categories") { setView("home"); return; }
        if (state.page === "game") { closeGame(); return; }
      }
      if (e.key === "F5" || (e.ctrlKey && e.key.toLowerCase() === "r")) e.preventDefault();
      // 设置页是独立界面：除 Esc（上面已处理）外的快捷键一律不抢，
      // 免得滚动/切页签时顺带把大厅的焦点、背景甚至游戏启动状态也改了
      if (state.settingsOpen || state.view === "categories") return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        const box = state.view === "categories" ? el.catQuery : el.search;
        box.focus();
        box.select();
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
          // 只有正看着这个游戏时才弹候选面板；
          // 大厅里、以及设置页里都只提示一句，别把面板盖到别的界面上
          if (state.focus === payload.id && state.page === "game" && !payload.quiet
              && !state.settingsOpen) {
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
        } else if (event === "vntext:status") {
          if (el.vntextPanel.classList.contains("open")) renderVntextPanel(payload);
        } else if (event === "vntext:line") {
          if (state.settingsOpen && state.settingsTab === "vntext") renderGlossary();
          if (el.vntextPanel.classList.contains("open")) refreshVntext();
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
    // 作用域：恢复上次看的分类 / 状态 / 厂商（分类被删掉就退回全部）
    try {
      const raw = localStorage.getItem("aurora.scope");
      const saved = raw ? JSON.parse(raw) : null;
      const usable = saved && saved.type && saved.type !== "all"
        && (saved.type !== "shelf" || state.shelves.some((s) => s.id === saved.value));
      if (usable) state.scope = { type: saved.type, value: saved.value || "" };
    } catch (_) { /* ignore */ }
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
