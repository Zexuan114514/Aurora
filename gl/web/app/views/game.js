/* Aurora 前端 · 游戏页视图（P4.3-k）
 *
 * 游戏页的**渲染面**：LOGO / 标题 / 信息条 / 简介 / 运行状态 / 数据来源，
 * 外加详情面板也要用的几个纯 helper（`chip` / `descText` / `detailBody`）。
 *
 * 约定与前几块视图一致：视图只 import core；主模块的取数与副作用
 * （当前游戏、背景缩放 UI、实时计时、资料源名字）由 `createGameView(ctx)` 注入，
 * 且一律用**箭头延迟取值**包装 —— 避开 P4.3-c 的 TDZ 坑。
 */
import { el, esc } from "../core/dom.js";
import { state } from "../core/store.js";
import { hours, clock, sessionSeconds } from "../core/time.js";

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
 *   syncBgZoomUi(game),   // 背景缩放滑杆与数值（主模块）
 *   startLiveTicker(),    // 运行中的秒表（主模块）
 *   sourceName(id),       // 资料源显示名（主模块）
 * }
 */
export function createGameView(ctx) {
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
    ctx.syncBgZoomUi(g);

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
      if (g.data_source) parts.push(ctx.sourceName(g.data_source));
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

  return { renderGameContent };
}
