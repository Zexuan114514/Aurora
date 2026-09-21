/* Aurora 游戏启动器 · 前端主模块（P4.1 起是 ES 模块）
 * 桥接调用统一走 ./app/core/api.js；后续视图会继续拆到 ./app/views/。
 */
import { call } from "./app/core/api.js";
import { createCategoriesView } from "./app/views/categories.js";
import { createSettingsView, LE_URL } from "./app/views/settings.js";
import { createRing, layoutReadout, hallKeysOf } from "./app/views/hall.js";
import { createGameView } from "./app/views/game.js";
import { createSourcesView } from "./app/views/sources.js";
import { createVntextView } from "./app/views/vntext.js";
import { createToolbarView } from "./app/views/toolbar.js";
import { createEventRouter } from "./app/core/events.js";
import { createActions } from "./app/core/actions.js";
import { bindWindowControls } from "./app/core/window.js";
import { createBackgroundView } from "./app/views/background.js";
import { $, el, missingIds, esc, imgHtml } from "./app/core/dom.js";
import { openPanel, closePanel, closeAll } from "./app/core/panels.js";
import { hours } from "./app/core/time.js";
import { state, findGame, upsertGame, pushGame, setBusy, patchGame,
         ADD_KEY } from "./app/core/store.js";
import { STATUS_LABEL, STATUS_GLYPH, STATUS_ORDER,
         visibleGames } from "./app/core/query.js";

/* ============================================================
   Aurora 游戏启动器 · 前端逻辑
   ============================================================ */

  // 最小尺寸由后端按显示器缩放比例钳制（见 gl/api.py: resize_apply）
  /* 记录找不到的元素：HTML 与 JS 对不上时报出来，而不是整页静默死掉 */
  /* P4.3：元素表与 $ 在 ./app/core/dom.js（视图模块也要用同一份） */

  let pywebviewReady = false;
  let toastTimer = null;

  /* ---------------------------------------------------------- 工具 */
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


  /* 时长 / 时钟 / 会话时间戳在 ./app/core/time.js（P4.3-k） */
  /* 背景层（双缓冲 / 淡入 / 兜底渐变）在 ./app/views/background.js（P4.3-s） */

  /* ---------------------------------------------------------- 渲染 */
  /* 筛选 / 排序 / 作用域的纯逻辑在 ./app/core/query.js（P4.3-q） */

  /* imgHtml（图片回退链）在 ./app/core/dom.js（P4.3-l） */

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

  /* coverCandidates（封面候选链）在 ./app/views/game.js（P4.3-m） */

  /* ---------------------------------------------------------- 大厅 */
  /* ADD_KEY（「＋ 导入游戏」占位键）在 ./app/core/store.js（P4.3-p） */

  /* P4.2：游戏实体统一从 store 里找（本地同名函数保留，调用点不用动） */
  const currentGame = () => findGame(state.focus) || null;

  const hallKeys = () => {
    /* 键列表算法在 ./app/views/hall.js（P4.3-h）；可见游戏仍由这里筛 */
    return hallKeysOf(visibleGames().map((g) => g.id), ADD_KEY);
  };

  /* ---------- 大厅：绕竖轴的一圈封面（循环队列） ----------
     所有封面排在一根竖轴的圆周上，只有一张正对用户；越远的越小、越暗、
     越往轴里倾斜，看上去像整圈封面在眼前转动。列表首尾相接：
     从最后一张继续往前，会绕回第一张（末尾的「＋ 导入游戏」同样在环上）。
     位置每帧由 JS 计算，所以拖动可以跟手、松手再吸附。

     P4.3-j：环本体（运行期状态、测量、帧循环、拖动 / 滚轮 / 快捷键）全在
     ./app/views/hall.js 的 createRing 里；主模块只提供键列表、每格内容，以及
     「换焦点 / 进游戏页 / 开玩 / 开菜单」这几个回调。回调一律用箭头延迟取值，
     避开 P4.3-c 那种 `const` 还没初始化就被取走的 TDZ 坑。 */
  const ring = createRing({
    addKey: ADD_KEY,
    keys: () => hallKeys(),
    tile: (key) => ringTileOf(key),
    onFocus: (key, opts) => setFocus(key, opts),
    onEnter: (id) => enterGame(id),
    onPlay: (id) => playGame(id),
    onAddMenu: (tile) => openAddMenu(tile),
  });

  /* 大厅里的一项：游戏封面，或末尾的「导入游戏」色块（只管内容，位置由 views/hall.js 摆） */
  function tileInner(game) {
    if (!game) return `<span class="gi-card"></span>`;
    if (game === ADD_KEY) {
      return `<span class="gi-card">
        <svg viewBox="0 0 24 24" class="ic"><path d="M12 5v14M5 12h14"/></svg>
        <span>导入游戏</span>
        <span class="gi-ring"></span>
      </span>`;
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
    return `<span class="gi-card">
      <span class="gi-cover">${imgHtml("", coverSources(game))}<b>${letter}</b></span>
      <span class="veil"></span>
      ${badges.length ? `<span class="gi-badges">${badges.join("")}</span>` : ""}
      <span class="gi-ring"></span>
    </span>`;
  }

  /* 一格的「内容」：封面块，或末尾的「＋ 导入游戏」色块。
     节点复用、顺序与位置都在 ./app/views/hall.js（P4.3-j），这里只算
     html / 忙标记 / 标题，交给 ring.sync() 摆。 */
  function ringTileOf(key) {
    const game = key === ADD_KEY ? ADD_KEY : state.games.find((g) => g.id === key);
    const busy = !!game && game !== ADD_KEY
      && (game.metadata_state === "searching" || state.busy[game.id]);
    return {
      html: tileInner(game),
      busy,
      title: key === ADD_KEY ? "导入游戏" : ((game && game.name) || ""),
    };
  }

  function renderHall() {
    const list = visibleGames();
    const hasGames = state.games.length > 0;
    el.empty.hidden = hasGames;
    el.hall.hidden = !hasGames;
    if (state.page === "game") el.hall.hidden = true;
    if (!hasGames) {
      ring.clear();
      return;
    }
    const keys = hallKeys();
    if (!keys.includes(state.focus)) {
      state.focus = keys[0];
    }
    const listChanged = ring.sync(keys);
    syncFocusUi();
    // 等新 DOM 完成布局再摆位；列表换了就直接就位，免得从旧位置转一大圈
    requestAnimationFrame(() => ring.update(listChanged));
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

  /* 焦点变化 → 背景延迟淡入 + 预取邻居：在 ./app/views/background.js（P4.3-s） */
  function setFocus(id, opts = {}) {
    if (!id || id === state.focus) {
      if (opts.scroll !== false && !ring.dragging()) ring.update();
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
    gameView.renderGameContent();
    syncFocusUi();
    // 拖动过程中焦点由手指决定，别再让环拉回 state.focus
    if (opts.scroll !== false && !ring.dragging()) ring.update();
    background.scheduleBackground();
    if (opts.persist !== false) {
      try { localStorage.setItem("aurora.focus", state.focus); } catch (_) {}
    }
  }

  /* 大厅「进游戏页」：id 省略 = 当前焦点（views/hall.js 的点击与回车走这里） */
  function enterGame(id) {
    if (id) {
      if (state.focus !== id) setFocus(id);
      openGame(id);
      return;
    }
    openGame();
  }

  /* 大厅「直接开玩」：双击封面、或在游戏页按回车 */
  function playGame(id) {
    if (id) {
      setFocus(id);
      openGame(id);
    }
    actions.togglePlay();
  }

  /* 大厅 ↔ 游戏页 */
  function openGame(id) {
    if (id) state.focus = id;
    if (!currentGame()) return;
    state.page = "game";
    gameView.renderGameContent();
    el.hall.hidden = true;
    el.view.hidden = false;
    document.body.classList.add("page-game");
    closeAll();
    background.scheduleBackground();
  }

  function closeGame() {
    state.page = "hall";
    el.view.hidden = true;
    el.hall.hidden = state.games.length === 0;
    document.body.classList.remove("page-game");
    renderHall();
  }

  /* 游戏页（渲染面 + 背景面板 + 详情面板）在 ./app/views/game.js
     （P4.3-k / P4.3-l）；这里只把取数与副作用注入进去 */
  const gameView = createGameView({
    currentGame: () => currentGame(),
    startLiveTicker: () => actions.startLiveTicker(),
    statusOrder: () => STATUS_ORDER,
    statusLabel: () => STATUS_LABEL,
    render: (...a) => render(...a),
    toast: (...a) => toast(...a),
    modal: (...a) => modal(...a),
    chooseBackground: (...a) => background.chooseBackground(...a),
    setGameStatus: (...a) => categories.setGameStatus(...a),
    refreshLibrary: (...a) => actions.refreshLibrary(...a),
    closeGame: (...a) => closeGame(...a),
    leUrl: LE_URL,
  });

  /* 游戏动作（导入 / 整库刷新 / 启动结束 / 批量 / 秒表）在 ./app/core/actions.js（P4.3-u） */
  const actions = createActions({
    render: (...a) => render(...a),
    setFocus: (...a) => setFocus(...a),
    closeGame: (...a) => closeGame(...a),
    toast: (...a) => toast(...a),
    currentGame: () => currentGame(),
    applySettingsToUi: (...a) => settingsView.applySettingsToUi(...a),
    renderSources: (...a) => sourcesView.renderSources(...a),
    applySourcesHint: (...a) => sourcesView.applySourcesHint(...a),
    refreshShelves: (...a) => categories.refreshShelves(...a),
  });

  /* 背景层与背景面板在 ./app/views/background.js（P4.3-s） */
  const background = createBackgroundView({
    currentGame: () => currentGame(),
    hallKeys: () => hallKeys(),
    syncBgZoomUi: (...a) => gameView.syncBgZoomUi(...a),
    renderBgPanel: (...a) => gameView.renderBgPanel(...a),
    toast: (...a) => toast(...a),
  });

  function render() {
    renderHall();
    gameView.renderGameContent();
    document.body.classList.toggle("settings-open", state.settingsOpen);
    $("btnSettings").classList.toggle("on", state.settingsOpen);
    for (const btn of el.viewSwitch.querySelectorAll(".vs-btn")) {
      btn.classList.toggle("on", btn.dataset.view === state.view);
      btn.disabled = state.settingsOpen;
    }
    toolbar.syncScopePill();
    // 视图可见性只在这里决定：设置 / 分类 / 游戏页 / 大厅，互斥且一定会恢复
    const showSettings = state.settingsOpen;
    const showCategories = !showSettings && state.view === "categories";
    el.settingsView.hidden = !showSettings;
    el.categoriesView.hidden = !showCategories;
    if (showSettings || showCategories) {
      el.hall.hidden = true;
      el.view.hidden = true;
      el.empty.hidden = true;
      if (showCategories) categories.renderCategories();
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

  function setView(name) {
    const next = name === "categories" ? "categories" : "home";
    state.view = next;
    state.organizing = false;
    state.selected.clear();
    if (state.settingsOpen) state.settingsOpen = false;
    closeAll();
    render();
    if (next === "home") ring.update();
  }
  /* 分类工作区（左栏 / 标题 / 封面墙 / 批量条 + 事件绑定）
     在 ./app/views/categories.js（P4.3-b / P4.3-v） */

  /* 作用域胶囊 / 作用域菜单 / 排序菜单在 ./app/views/toolbar.js（P4.3-q） */
  const toolbar = createToolbarView({
    render: (...a) => render(...a),
    ringUpdate: () => { if (state.view === "home") ring.update(); },
    renderHall: (...a) => renderHall(...a),
    setView: (...a) => setView(...a),
    refreshShelves: (...a) => categories.refreshShelves(...a),
    setFocus: (...a) => setFocus(...a),
    openGame: (...a) => openGame(...a),
    currentGame: () => currentGame(),
    toast: (...a) => toast(...a),
  });

  /* 分类工作区的渲染、动作与绑定都在 ./app/views/categories.js（P4.3-b / P4.3-v） */
  const categories = createCategoriesView({
    render: (...a) => render(...a),
    renderHall: (...a) => renderHall(...a),
    setScope: (...a) => toolbar.setScope(...a),
    syncSortMenu: (...a) => toolbar.syncSortMenu(...a),
    renderDetail: (...a) => gameView.renderDetail(...a),
    setFocus: (...a) => setFocus(...a),
    openPanel: (node) => openPanel(node),
    coverSources: (...a) => coverSources(...a),
    toast: (...a) => toast(...a),
    modal: (...a) => modal(...a),
    cssEscape: (...a) => cssEscape(...a),
  });


  /* ---------------------------------------------------------- 游戏内翻译 */
  /* 面板渲染 / 设置页那栏 / 术语表 / OCR 框选 / 钩子查找器全在
     ./app/views/vntext.js（P4.3-p）；这里只注入提示 */
  const vntextView = createVntextView({
    toast: (...a) => toast(...a),
  });

  /* 面板与设置栏的渲染在 ./app/views/vntext.js（P4.3-p） */

  /* 状态刷新 / 术语表在 ./app/views/vntext.js（P4.3-p） */

  /* 面板开关与 OCR 框选在 ./app/views/vntext.js（P4.3-p） */

  /* 事件绑定（面板按钮 / hook 查找器 / 设置栏 / 术语表）在 ./app/views/vntext.js（P4.3-p） */

  /* ---------------------------------------------------------- 设置页 */
  /* 设置页整块（P4.3-c 开刀、P4.3-t 收口）在 ./app/views/settings.js。
     ctx 里一律用箭头延迟取值：这些 helper 有些是 const（定义在本行之后），
     直接传引用会在模块初始化时踩 TDZ（实测整页挂掉，e2e 3/13）。 */
  const settingsView = createSettingsView({
    render: (...a) => render(...a),
    toast: (...a) => toast(...a),
    ringApplyLayout: () => ring.applyLayout(),
    applyKenBurns: (...a) => background.applyKenBurns(...a),
    openSourcePanel: (...a) => sourcesView.openSourcePanel(...a),
    openSteamPanel: (...a) => sourcesView.openSteamPanel(...a),
    startRefreshAll: (...a) => actions.startRefreshAll(...a),
    startTranslateAll: (...a) => actions.startTranslateAll(...a),
    refreshLibrary: (...a) => actions.refreshLibrary(...a),
    refreshVntext: (...a) => vntextView.refresh(...a),
    renderGlossary: (...a) => vntextView.renderGlossary(...a),
  });
  const { setSettingsTab, openSettings, closeSettings, refreshSettingsPanes } = settingsView;

  /* 背景面板与缩放 UI 在 ./app/views/game.js（P4.3-l） */

  /* 背景缩放（滑杆 → 视图 → 防抖持久化）在 ./app/views/background.js（P4.3-s） */

  /* ---------------------------------------------------------- 详情面板 */
  /* 详情面板在 ./app/views/game.js（P4.3-l） */

  /* ---------------------------------------------------------- 封面面板 */
  /* 换封面面板的渲染与开关在 ./app/views/game.js（P4.3-m / P4.3-o） */

  /* ---------------------------------------------------------- Steam 扫描 */
  /* 扫描 / 列表 / 导入在 ./app/views/sources.js（P4.3-n） */

  /* ---------------------------------------------------------- 批量重新抓取 */

  /* ---------------------------------------------------------- 获取游戏 */
  /* 资源站与下载设置面板在 ./app/views/sources.js（P4.3-n） */

  /* ---------------------------------------------------------- 批量任务 / 候选匹配 */
  /* 批量重抓与批量翻译在 ./app/core/actions.js（P4.3-u） */
  /* sourceName / 候选列表（renderMatches）/ 跳转搜索（renderMatchLinks）
     在 ./app/views/game.js（P4.3-m） */

  /* ---------------------------------------------------------- 资料源管理 */
  /* 资料源列表 / 自定义源表单在 ./app/views/sources.js（P4.3-n） */

  /* ---------------------------------------------------------- 事件：面板开关 */
  /* openPanel / closePanel / closeAll 在 ./app/core/panels.js（P4.3-o） */

  /* 资料源 / Steam / 获取游戏三块面板在 ./app/views/sources.js（P4.3-n） */
  const sourcesView = createSourcesView({
    toast: (...a) => toast(...a),
    importGames: (...a) => actions.importGames(...a),
    refreshLibrary: (...a) => actions.refreshLibrary(...a),
    render: (...a) => render(...a),
  });

  /* 动作（导入 / 整库刷新 / 启动结束 / 秒表）在 ./app/core/actions.js（P4.3-u） */
  /* chooseBackground / pickLocalBackground 在 ./app/views/background.js（P4.3-s） */
  /* 手动匹配流程（openMatchPanel / doSearch / researchGame / applyCandidate）与
     单个游戏的转区面板（renderLocalePanel / openLocalePanel / saveGameLocale）
     在 ./app/views/game.js（P4.3-m / P4.3-u） */

  /* applySettingsToUi / saveSetting 在 ./app/views/settings.js（P4.3-t） */

  /* ---------------------------------------------------------- 窗口拖拽 / 缩放 */
  /* 窗口控制（拖动 / 缩放 / 最小化最大化 / 失焦清理）在 ./app/core/window.js（P4.3-s） */
  /* 背景缩放滑杆与图片回退链在 ./app/views/background.js（P4.3-s） */

  /* ---------------------------------------------------------- 绑定 */
  /* 排序菜单的选中态与开合在 ./app/views/toolbar.js（P4.3-q） */

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
    $("btnImport2").onclick = () => actions.importGames();
    el.play.onclick = () => actions.togglePlay();
    el.btnBack.onclick = closeGame;

    // 大厅交互（悬停 / 单击 / 双击 / 横向拖动 / 滚轮）整块在
    // ./app/views/hall.js（P4.3-j）；这里只把事件挂上去，时机与拆分前一致
    ring.bind();

    // 窗口尺寸变化后重新把焦点封面摆到正中
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => ring.update(true), 80);
    });
    // 从设置 / 分类页回到大厅时舞台尺寸才确定，这里补一次量
    if (window.ResizeObserver) {
      new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => ring.update(true), 80);
      }).observe(el.hallViewport);
    }

    /* 背景面板（按钮 / 缩略图 / 缩放滑杆）在 ./app/views/background.js（P4.3-s） */

    // 详情 / 候选匹配 / 更多菜单 / 转区 / 换封面：./app/views/game.js（P4.3-w）
    gameView.bind();

    // 设置页整块（页签 / 网络 / 转区 / 外观 / 翻译 / 资料源 / 备份）
    // 在 ./app/views/settings.js（P4.3-t）
    settingsView.bind();

    // 视图切换 / 作用域菜单 / 搜索 / 排序：./app/views/toolbar.js（P4.3-w）
    toolbar.bind();

    // 分类工作区（左栏 / 封面墙 / 批量条 / 搜索排序同步）在
    // ./app/views/categories.js（P4.3-b / P4.3-v）
    categories.bind();
    vntextView.bind();

    // Steam / 获取游戏 / 资料源管理 / 末尾方块菜单：./app/views/sources.js（P4.3-w）
    sourcesView.bind();

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
      // 大厅快捷键（← → / Home / End / Enter）在 ./app/views/hall.js（P4.3-j）
      if (ring.handleKey(e)) return;
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
  /* 14 个主题的处理表在 ./app/core/events.js（P4.3-r）；
     这里只注入渲染、焦点与各视图的更新口子（一律箭头延迟取值） */
  const events = createEventRouter({
    render: (...a) => render(...a),
    renderHall: (...a) => renderHall(...a),
    refreshLibrary: (...a) => actions.refreshLibrary(...a),
    setFocus: (...a) => setFocus(...a),
    scheduleBackground: (...a) => background.scheduleBackground(...a),
    currentGame: () => currentGame(),
    upsertGame: (...a) => upsertGame(...a),
    pushGame: (...a) => pushGame(...a),
    patchGame: (...a) => patchGame(...a),
    setBusy: (...a) => setBusy(...a),
    findGame: (...a) => findGame(...a),
    toast: (...a) => toast(...a),
    openCandidates: (...a) => gameView.openCandidates(...a),
    updateSteamHint: (...a) => sourcesView.updateSteamHint(...a),
    vntext: {
      renderPanel: (...a) => vntextView.renderPanel(...a),
      onHookSearch: (...a) => vntextView.onHookSearch(...a),
      renderGlossary: (...a) => vntextView.renderGlossary(...a),
      refresh: (...a) => vntextView.refresh(...a),
    },
  });

  window.__aurora = {
    /* 自检用：大厅环形队列状态 / 布局读数 —— 取数逻辑在 ./app/views/hall.js（P4.3-d） */
    ring: () => ring.readout(),
    layout: () => layoutReadout({
      row: el.hallRow,
      viewport: el.hallViewport.getBoundingClientRect(),
      layoutName: ring.layoutName(),
      flatClass: document.body.classList.contains("hall-flat"),
    }),
    /* 后端推送：14 个主题的处理表在 ./app/core/events.js（P4.3-r） */
    emit: (event, payload) => events.emit(event, payload),
  };

  /* ---------------------------------------------------------- 启动 */
  async function boot() {
    // 逐个绑定并兜住异常：某一处出错也不至于让整个界面不响应
    for (const [name, fn] of [
      ["窗口", () => bindWindowControls({ onPointerReset: () => ring.endDrag() })],
      ["背景", () => background.bind()],
      ["界面", bindUi],
    ]) {
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
      await actions.refreshLibrary();
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
    background.scheduleBackground();
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
