/* Aurora 前端 · 游戏动作（P4.3-u）
 *
 * 「对库和游戏做的事」集中在这里：导入、整库刷新、启动 / 结束、批量重抓与批量翻译，
 * 以及运行中的秒表。它们都要调后端（core/api）并改 store，所以放在 core 而不是某个视图。
 *
 * ctx = { render, setFocus, closeGame, toast, currentGame,
 *         applySettingsToUi, renderSources, applySourcesHint, refreshShelves }
 */
import { call } from "./api.js";
import { $ } from "./dom.js";
import { state, ADD_KEY, replaceGames } from "./store.js";
import { clock, sessionSeconds } from "./time.js";

export function createActions(ctx) {
  async function importGames() {
    try {
      const res = await call("pick_executable");
      if (!res || res.cancelled) return;
      if (!res.ok) { ctx.toast("导入失败：" + (res.error || "未知错误")); return; }
      const games = res.games || [];
      if (!games.length) return;
      await refreshLibrary();
      ctx.render();
      ctx.setFocus(games[games.length - 1].id);
      ctx.closeGame();
      ctx.toast(`已导入 ${games.length} 个游戏`);
    } catch (e) { ctx.toast("导入失败：" + e.message); }
  }

  /** 整库刷新：后端 bootstrap 是唯一来源，前端只做回填与重绘。 */
  async function refreshLibrary() {
    const data = await call("bootstrap");
    replaceGames(data.games);
    state.settings = data.settings || {};
    state.sources = data.sources || [];
    state.version = data.version || "";
    if (state.focus && state.focus !== ADD_KEY && !ctx.currentGame()) {
      state.focus = state.games[0]?.id || ADD_KEY;
    }
    ctx.applySettingsToUi();
    ctx.renderSources();
    ctx.applySourcesHint();
    await ctx.refreshShelves();
  }

  /** 「开始游戏 / 结束游戏」：结束走 stop，启动失败要说清楚是哪一种失败。 */
  async function togglePlay() {
    const g = ctx.currentGame();
    if (!g) return;
    if (g.running) {
      await call("stop", g.id);
      ctx.toast("已结束游戏进程");
      return;
    }
    const res = await call("launch", g.id);
    if (!res || !res.ok) {
      const map = {
        "missing-exe": "找不到可执行文件，可能已被移动或删除。",
        "already-running": "游戏已在运行中。",
      };
      ctx.toast(map[res && res.error] || "启动失败：" + ((res && res.error) || "未知错误"));
      return;
    }
    ctx.toast("游戏已启动");
    const game = state.games.find((x) => x.id === g.id);
    if (game) { game.running = true; ctx.render(); }
  }

  async function startRefreshAll() {
    if (state.batch) { ctx.toast("已经有一个批量任务在跑"); return; }
    // 先占位，避免后端第一批进度事件比这里更早到达而被丢掉
    state.batch = { kind: "refresh", done: 0, total: 0 };
    const res = await call("refresh_all_metadata");
    if (!res || !res.ok) {
      state.batch = null;
      ctx.toast(res && res.error === "empty" ? "库里还没有游戏" : "启动失败，请稍后再试");
      return;
    }
    state.batch.total = res.total;
    $("refreshHint").textContent = `0/${res.total}`;
    ctx.toast(`开始重新抓取 ${res.total} 个游戏的资料`);
  }

  async function startTranslateAll() {
    if (state.batch) { ctx.toast("已经有一个批量任务在跑"); return; }
    state.batch = { kind: "translate", done: 0, total: 0 };
    const res = await call("translate_all_descriptions");
    if (!res || !res.ok) {
      state.batch = null;
      ctx.toast(res && res.error === "empty" ? "库里还没有游戏" : "启动失败，请稍后再试");
      return;
    }
    state.batch.total = res.total;
    $("translateHint").textContent = `0/${res.total}`;
    ctx.toast(`开始翻译 ${res.total} 个游戏的简介`);
  }

  /* 运行中的实时计时（只改那一颗 chip，避免整页重绘） */
  let liveTimer = null;
  function startLiveTicker() {
    if (liveTimer) return;
    liveTimer = setInterval(() => {
      const node = document.getElementById("chipLive");
      if (!node) return;
      const g = ctx.currentGame();
      if (!g || !g.running) return;
      node.innerHTML = `运行中 · <b>${clock(sessionSeconds(g))}</b>`;
    }, 1000);
  }

  return { importGames, refreshLibrary, togglePlay,
           startRefreshAll, startTranslateAll, startLiveTicker };
}
