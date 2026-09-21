/* Aurora 前端 · 游戏页视图（P4.3-k）
 *
 * 游戏页的**渲染面**：LOGO / 标题 / 信息条 / 简介 / 运行状态 / 数据来源，
 * 外加详情面板也要用的几个纯 helper（`chip` / `descText` / `detailBody`）。
 *
 * 约定与前几块视图一致：视图只 import core；主模块的取数与副作用
 * （当前游戏、背景缩放 UI、实时计时、资料源名字）由 `createGameView(ctx)` 注入，
 * 且一律用**箭头延迟取值**包装 —— 避开 P4.3-c 的 TDZ 坑。
 */
import { $, el, esc, imgHtml } from "../core/dom.js";
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
 *   openPanel(node),      // 面板开合还是主模块的事（P4.3-m 只搬渲染）
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
    ctx.openPanel(el.matchPanel);
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

  return { renderGameContent, renderBgPanel, syncBgZoomUi, renderDetail,
           renderCoverPanel, matchHintText, renderQuickQueries, renderMatches,
           openCandidates };
}
