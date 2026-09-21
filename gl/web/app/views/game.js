/* Aurora 前端 · 游戏页视图（P4.3-k）
 *
 * 游戏页的**渲染面**：LOGO / 标题 / 信息条 / 简介 / 运行状态 / 数据来源，
 * 外加详情面板也要用的几个纯 helper（`chip` / `descText` / `detailBody`）。
 *
 * 约定与前几块视图一致：视图只 import core；主模块的取数与副作用
 * （当前游戏、背景缩放 UI、实时计时、资料源名字）由 `createGameView(ctx)` 注入，
 * 且一律用**箭头延迟取值**包装 —— 避开 P4.3-c 的 TDZ 坑。
 */
import { call } from "../core/api.js";
import { $, el, esc, imgHtml } from "../core/dom.js";
import { closeAll, closePanel, openPanel } from "../core/panels.js";
import { state } from "../core/store.js";
import { hours, clock, sessionSeconds, stamp } from "../core/time.js";

/** 一枚信息条小胶囊（详情面板也用它）。 */
export function chip(text, accent) {
  return `<span class="chip${accent ? " accent" : ""}">${esc(text)}</span>`;
}

/** 简介文本：显示原文还是译文由 show_original 决定。 */
export function descText(g) {
  const orig = (g.description_original || "").trim();
  if (state.settings.show_original && orig) return orig;
  return g.description || g.description_translated || g.about?.slice(0, 220) || "";
}

/** 「显示原文 / 译文」按钮：只有原文与译文都在、且两者不同时才出现。 */
export function updateShowOriginalBtn(g) {
  const btn = el.showOriginal;
  if (!btn) return;
  const hasBoth = !!(g && g.description_translated
    && (g.description_original || "").trim()
    && g.description_translated !== g.description_original);
  btn.hidden = !hasBoth;
  if (hasBoth) btn.textContent = state.settings.show_original ? "显示译文" : "显示原文";
}

/** 详情正文：有译文时跟着卡片显示译文，否则用长简介（原文）。 */
export function detailBody(g) {
  const shown = descText(g);
  if (g.description_translated) return shown || g.about || "";
  return g.about || shown || "";
}

/**
 * 游戏页渲染。
 *
 * ctx = {
 *   currentGame(),        // 当前焦点游戏（主模块的 currentGame）
 *   startLiveTicker(),    // 运行中的秒表（主模块）
 *   statusOrder(),        // 游玩状态的顺序（主模块的 STATUS_ORDER）
 *   statusLabel(),        // 游玩状态的文案（主模块的 STATUS_LABEL）
 *   render(),             // 整页重绘（主模块）
 *   toast(msg, ms),       // 提示
 *   modal(opts),          // 输入/确认对话框（主模块）
 *   chooseBackground(url, kind),  // 截图设为背景（views/background.js）
 *   setGameStatus(id, status),    // 详情面板改游玩状态（views/categories.js）
 *   refreshLibrary(),     // 移除游戏后刷新（core/actions.js）
 *   closeGame(),          // 回大厅（主模块）
 *   leUrl,                // Locale Emulator 下载页（views/settings.js 导出）
 * }
 */
export function createGameView(ctx) {
  /** 资料源显示名：列表里有就用列表里的名字，没有就用 id 本身。 */
  function sourceName(id) {
    const row = (state.sources || []).find((s) => s.id === id);
    if (row) return row.name;
    return id ? id : "";
  }

  /* 背景缩放 UI 与状态同步 */
  function syncBgZoomUi(game) {
    const g = game || ctx.currentGame();
    if (!g) return;
    const scale = Math.round((Number(g.bg_scale) || 1) * 100);
    $("bgZoom").value = Math.min(300, Math.max(100, scale));
    $("bgZoomVal").textContent = scale + "%";
  }

  /* 游戏页（以及大厅底部的）文字内容 */
  function renderGameContent() {
    const g = ctx.currentGame();
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
    if (g.running) ctx.startLiveTicker();

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

  /* 背景图面板：一排可选的壁纸（点一张即应用） */
  function renderBgPanel() {
    const g = ctx.currentGame();
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

  /* 详情面板：信息表 + 游玩记录 + 截图墙（截图点一下可设为背景） */
  function renderDetail() {
    const g = ctx.currentGame();
    if (!g) return;
    el.dTitle.textContent = g.name;
    el.dSub.textContent = g.name_original && g.name_original !== g.name
      ? g.name_original : g.exe_name;

    const STATUS_ORDER = ctx.statusOrder();
    const STATUS_LABEL = ctx.statusLabel();
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

  /* 换封面面板：一排候选，点一张就换（打开与关闭仍由主模块的面板管路负责） */
  function renderCoverPanel() {
    const g = ctx.currentGame();
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

  /** 打开换封面面板（先全关，避免叠在别的浮层上）。 */
  function openCoverPanel() {
    closeAll();
    renderCoverPanel();
    openPanel(el.coverPanel);
  }

  /* ---------------------------------------------------------- 手动匹配 */
  const matchHintText = (text) => { el.matchHint.textContent = text || ""; };

  /* 快捷词：文件名推断出来的关键词 + 资料源给的各个名字，点一下就换个写法再搜 */
  function renderQuickQueries(g) {
    const seen = new Set();
    const out = [];
    const push = (value) => {
      const text = String(value || "").trim();
      if (!text || seen.has(text.toLowerCase())) return;
      seen.add(text.toLowerCase());
      out.push(text);
    };
    (g && g.queries || []).forEach(push);
    push(g && g.name_original);
    push(g && g.name_cn);
    push(g && g.name);
    const list = out.slice(0, 5);
    el.matchQuick.hidden = !list.length;
    el.matchQuick.innerHTML = list.map((q) =>
      `<button class="quick-chip" data-q="${esc(q)}">${esc(q)}</button>`).join("");
  }

  /* 候选列表：后端已按匹配度从高到低排好，点一条就应用（不自动采纳） */
  function renderMatches(candidates, query) {
    el.matchQuery.value = query || "";
    renderMatchLinks(query);
    const rows = candidates || [];
    const g = ctx.currentGame();
    // 当前已应用的那一条：新记录有 data_source/source_id，老记录用 appid / 详情页地址兜底
    const curUrl = String((g && (g.store_url || g.source_url)) || "");
    const curSource = (g && g.data_source)
      || (/steampowered|steamstatic/.test(curUrl) ? "steam"
        : /vndb\.org/.test(curUrl) ? "vndb"
          : /bgm\.tv/.test(curUrl) ? "bangumi" : "");
    const curId = String((g && (g.source_id || g.appid))
      || curUrl.replace(/\/+$/, "").split("/").pop() || "");
    const isCurrent = (c) => Boolean(curId && c.source === curSource
      && String(c.source_id) === curId);
    if (!rows.length) {
      el.matchList.innerHTML =
        `<div class="list-empty">没有找到候选，换个关键词试试，或检查设置里的资料源。</div>`;
      return;
    }
    el.matchList.innerHTML = rows.map((c, index) => `
      <button class="match-item${index === 0 && rows.length > 1 ? " best" : ""}"
              data-source="${esc(c.source)}"
              data-source-id="${esc(c.source_id)}" data-name="${esc(c.name)}">
        ${c.thumb ? `<img src="${esc(c.thumb)}" alt="" loading="lazy">` : `<img alt="">`}
        <div>
          <div class="mi-name">${esc(c.name)}${
            isCurrent(c) ? '<span class="mi-cur">当前</span>' : ""}${
            index === 0 && rows.length > 1 ? '<span class="mi-best">匹配度最高</span>' : ""}</div>
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

  /* 打开候选面板：候选按匹配度从高到低摆出来，等用户自己点（不自动采纳） */
  function openCandidates(rows, query, note) {
    renderQuickQueries(ctx.currentGame());
    renderMatches(rows, query);
    openPanel(el.matchPanel);
    if (rows && rows.length) {
      const best = Math.round((rows[0].score || 0) * 100);
      matchHintText(`共 ${rows.length} 条候选，按匹配度从高到低排列` +
        `（最高 ${best}%）——点一条就应用。`);
      $("matchRetry").hidden = true;
    } else {
      matchHintText(note || "没有找到候选：换个写法（中文名 / 日文原名 / 英文名）再搜。");
      $("matchRetry").hidden = !/网络/.test(note || "");
    }
    return Boolean(rows && rows.length);
  }

  /* 「⋯ → 手动匹配…」：预填名字（匹配过的用当前名字，没匹配的用文件名推断词）开面板并搜一次 */
  async function openMatchPanel() {
    const g = ctx.currentGame();
    if (!g) return;
    closeAll();
    // 已经匹配上的用当前名字搜（最准）；没匹配上的用文件名推断出的关键词
    const query = (g.metadata_state === "ok" && g.name)
      ? g.name : ((g.queries || [])[0] || g.name || "");
    renderQuickQueries(g);
    renderMatches([], query);
    el.matchList.innerHTML = `<div class="list-empty">正在搜索…</div>`;
    matchHintText(query ? `正在按「${query}」搜索…` : "");
    $("matchRetry").hidden = true;
    openPanel(el.matchPanel);
    if (query) await doSearch(query);
    else {
      matchHintText("输入游戏名（中文 / 日文原名 / 英文名都行）再点搜索。");
      el.matchQuery.focus();
    }
  }

  /* 手动搜索：只把候选列出来，库里的匹配结果要等用户点某一条才会变 */
  async function doSearch(query) {
    const g = ctx.currentGame();
    if (!g) return;
    const q = (query || "").trim();
    const btn = $("matchGo");
    btn.disabled = true;
    el.matchList.innerHTML = `<div class="list-empty">正在搜索…</div>`;
    matchHintText(q ? `正在搜索「${q}」…` : "正在按文件名推断的关键词搜索…");
    try {
      const res = await call("search", g.id, q || null);
      const asked = q || (res.queries || [])[0] || "";
      if (!openCandidates(res.candidates, asked, res.reason === "network"
          ? "网络不通，没能拿到候选；可以点「重试」再来一次。"
          : "没有找到候选：换个写法（中文名 / 日文原名 / 英文名）再搜。")) {
        ctx.toast("没有找到匹配结果");
      }
    } catch (e) {
      el.matchList.innerHTML =
        `<div class="list-empty">搜索出错，可以换个关键词重试。</div>`;
      matchHintText("搜索出错：" + e.message);
      $("matchRetry").hidden = false;
    } finally {
      btn.disabled = false;
    }
  }

  /* 「⋯ → 重新搜索游戏信息」：自动流程，匹配度够高就直接采纳（保持原样） */
  async function researchGame() {
    const g = ctx.currentGame();
    if (!g) return;
    ctx.toast("正在重新搜索…");
    try {
      const res = await call("search", g.id, null, true, false);
      if (res.applied) {
        if (res.game) Object.assign(g, res.game);
        closeAll();
        ctx.render();
        ctx.toast("已匹配：" + g.name);
        return;
      }
      closeAll();
      openCandidates(res.candidates, (res.queries || [])[0] || "",
                     "匹配置信度不足，请手动选择");
      ctx.toast("匹配置信度不足，请手动选择");
    } catch (e) {
      ctx.toast("搜索失败：" + e.message);
    }
  }

  /** 用户点了某条候选 → 让后端按这条重取资料。 */
  async function applyCandidate(item) {
    const g = ctx.currentGame();
    if (!g || !item) return;
    ctx.toast("正在获取资料…");
    const res = await call("apply_candidate", g.id, item.dataset.source,
                           item.dataset.sourceId, item.dataset.name, "manual");
    if (res.game) Object.assign(g, res.game);
    closeAll();
    ctx.render();
    ctx.toast("已应用：" + g.name);
  }

  /* ------------------------------------------------------------ 转区启动面板（单个游戏） */
  async function renderLocalePanel(game) {
    const g = game || ctx.currentGame();
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
    const g = ctx.currentGame();
    if (!g) return;
    closeAll();
    await renderLocalePanel(g);
    openPanel(el.localePanel);
  }

  /* 写回单个游戏的转区开关与配置 */
  async function saveGameLocale(enabled, guid) {
    const g = ctx.currentGame();
    if (!g) return;
    const res = await call("set_game_locale", g.id, !!enabled, guid || "");
    if (!res || !res.ok) { ctx.toast("保存转区设置失败"); return; }
    if (res.game) Object.assign(g, res.game);
    ctx.render();
    const usable = state.locale && state.locale.available;
    ctx.toast(enabled
      ? (usable ? "已开启转区启动" : "已开启：装好 Locale Emulator 后即可生效")
      : "已关闭转区启动");
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
    // 详情面板
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
        ctx.chooseBackground(shot.dataset.shot, shot.dataset.kind || "screenshot");
        ctx.toast("已设为背景");
      }
    });
    el.detailBody.addEventListener("change", (e) => {
      if (e.target.id === "detailStatus") {
        ctx.setGameStatus(e.target.dataset.id, e.target.value);
      }
    });

    // 候选匹配面板
    $("matchClose").onclick = () => closePanel(el.matchPanel);
    $("matchGo").onclick = () => doSearch(el.matchQuery.value.trim());
    el.matchQuery.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch(el.matchQuery.value.trim());
    });
    el.matchList.addEventListener("click", (e) => {
      const item = e.target.closest(".match-item");
      if (item) applyCandidate(item);
    });
    el.matchQuick.addEventListener("click", (e) => {
      const chip = e.target.closest("[data-q]");
      if (chip) doSearch(chip.dataset.q);
    });
    el.matchLinks.addEventListener("click", (e) => {
      const chip = e.target.closest("[data-link-source]");
      if (!chip) return;
      const query = el.matchQuery.value.trim();
      if (!query) { ctx.toast("先输入要搜索的名字"); return; }
      call("open_source_search", query, chip.dataset.linkSource).then((res) => {
        if (!res || !res.ok) ctx.toast("打不开搜索页：" + ((res && res.error) || ""));
      });
    });
    // 重试按输入框里的词再搜一次（手动面板里用户可能刚改过关键词）
    $("matchRetry").onclick = () => doSearch(el.matchQuery.value.trim() || null);

    // 更多菜单
    $("btnMore").onclick = () => {
      const hidden = el.moreMenu.hidden;
      closeAll();
      const g = ctx.currentGame();
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
      const g = ctx.currentGame();
      el.moreMenu.hidden = true;
      if (!g) return;
      const act = btn.dataset.act;
      if (act === "reveal") { call("reveal", g.id); }
      else if (act === "favorite") {
        const res = await call("toggle_favorite", g.id);
        if (res.game) Object.assign(g, res.game);
        ctx.render();
        ctx.toast(res.favorite ? "已加入收藏" : "已取消收藏");
      }
      else if (act === "rename") {
        const value = await ctx.modal({
          title: "重命名", body: "只改启动器里显示的名字，不动游戏文件。",
          input: true, value: g.name, okText: "保存",
        });
        if (value === null) return;
        if (!value) { ctx.toast("名字不能为空"); return; }
        const res = await call("rename_game", g.id, value);
        if (res.game) Object.assign(g, res.game);
        ctx.render();
        ctx.toast("已重命名");
      }
      else if (act === "name-reset") {
        const res = await call("reset_name", g.id);
        if (res.game) Object.assign(g, res.game);
        ctx.render();
        ctx.toast("已恢复自动命名，正在重新搜索…");
      }
      else if (act === "cover") { openCoverPanel(); }
      else if (act === "icon") {
        const res = await call("pick_custom_icon", g.id);
        if (!res || res.cancelled) return;
        if (!res.ok) { ctx.toast("设置图标失败：" + (res.error || "")); return; }
        Object.assign(g, res.game);
        ctx.render();
        ctx.toast("已设置自定义图标");
      } else if (act === "icon-reset") {
        const res = await call("clear_custom_icon", g.id);
        if (res.game) Object.assign(g, res.game);
        ctx.render();
        ctx.toast("已恢复默认图标");
      } else if (act === "store") {
        if (g.source_url) call("open_url", g.source_url);
        else ctx.toast("还没有匹配到条目");
      } else if (act === "research") { researchGame(); }
      else if (act === "match") { openMatchPanel(); }
      else if (act === "locale") { openLocalePanel(); }
      else if (act === "translate") {
        const res = await call("translate_game", g.id);
        if (!res || !res.ok) { ctx.toast("翻译启动失败"); return; }
        ctx.toast("正在翻译简介…");
      }
      else if (act === "args") {
        const value = await ctx.modal({
          title: "启动参数", body: "会追加在可执行文件之后，点下面的常用参数可快速加入。",
          input: true, value: g.launch_args || "", okText: "保存",
          presets: ["-windowed", "-fullscreen", "-dx11", "-dx12", "-novid", "-high"],
        });
        if (value !== null) {
          g.launch_args = value;
          await call("set_launch_args", g.id, value);
          ctx.toast("已保存启动参数");
        }
      } else if (act === "remove") {
        const ok = await ctx.modal({
          title: "移除游戏",
          body: `确定把「${g.name}」从库中移除吗？不会删除磁盘上的文件。`,
          okText: "移除",
        });
        if (!ok) return;
        await call("remove_game", g.id);
        await ctx.refreshLibrary();
        if (state.focus === g.id) {
          state.focus = state.games[0]?.id || ADD_KEY;
          if (state.page === "game") ctx.closeGame();
        }
        ctx.render();
        ctx.toast("已移除");
      }
    });

    // 单个游戏的转区面板
    $("locClose").onclick = () => closePanel(el.localePanel);
    $("locSwitch").onchange =
      (e) => saveGameLocale(e.target.checked, $("locProfile").value);
    $("locProfile").onchange =
      (e) => saveGameLocale($("locSwitch").checked, e.target.value);
    $("locPick").onclick = async () => {
      const res = await call("pick_locale_proc");
      if (!res || res.cancelled) return;
      if (!res.ok) { ctx.toast("这个路径不可用：" + ((res && res.error) || "")); return; }
      await renderLocalePanel();
      ctx.toast("已设置 Locale Emulator 路径");
    };
    $("locDownload").onclick = () => call("open_url", ctx.leUrl);

    // 换封面面板
    $("coverClose").onclick = () => closePanel(el.coverPanel);
    el.coverGrid.addEventListener("click", async (e) => {
      const item = e.target.closest("[data-cover]");
      if (!item) return;
      const g = ctx.currentGame();
      if (!g) return;
      const res = await call("set_cover", g.id, item.dataset.cover);
      if (res.game) Object.assign(g, res.game);
      renderCoverPanel();
      ctx.render();
      ctx.toast("已更换封面");
    });
    $("btnLocalCover").onclick = async () => {
      const g = ctx.currentGame();
      if (!g) return;
      const res = await call("pick_local_cover", g.id);
      if (!res || res.cancelled) return;
      if (!res.ok) { ctx.toast("选择失败：" + ((res && res.error) || "")); return; }
      Object.assign(g, res.game);
      renderCoverPanel();
      ctx.render();
      ctx.toast("已应用本地封面");
    };
    $("btnCoverReset").onclick = async () => {
      const g = ctx.currentGame();
      if (!g) return;
      const res = await call("clear_custom_cover", g.id);
      if (res.game) Object.assign(g, res.game);
      renderCoverPanel();
      ctx.render();
      ctx.toast("已恢复默认封面");
    };
  }

  return { renderGameContent, renderBgPanel, syncBgZoomUi, renderDetail,
           renderCoverPanel, openCoverPanel,
           matchHintText, renderQuickQueries, renderMatches,
           openCandidates,
           openMatchPanel, doSearch, researchGame, applyCandidate,
           renderLocalePanel, openLocalePanel, saveGameLocale,
           bind };
}
