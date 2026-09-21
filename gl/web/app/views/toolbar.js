/* Aurora 前端 · 工具条：作用域胶囊 / 作用域菜单 / 排序菜单（P4.3-q）
 *
 * 工具条只做「选范围、选排序」两件事，真正的筛选与排序在 core/query.js。
 * 这里负责：
 *   - 作用域胶囊的文案与「清除」按钮可见性
 *   - 作用域菜单（范围 / 自定义分类 / 按状态 / 按开发商）与它的定位
 *   - 排序菜单的选中态与定位
 *   - 事件绑定：视图切换、作用域菜单、搜索框与排序菜单
 *
 * ctx = { render, ringUpdate, renderHall, setView, refreshShelves,
 *         setFocus, openGame, currentGame, toast }
 */
import { $, el, esc } from "../core/dom.js";
import { closeAll } from "../core/panels.js";
import { ADD_KEY, state } from "../core/store.js";
import { STATUS_LABEL, STATUS_ORDER, scopeCount, scopeName, visibleGames } from "../core/query.js";

export function createToolbarView(ctx) {
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
    ctx.render();
    ctx.ringUpdate();
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

  /** 点胶囊：开着就收起，关着就先全关再弹出（与其它菜单互斥）。 */
  function toggleScopeMenu() {
    const wasHidden = el.scopeMenu.hidden;
    closeAll();
    if (wasHidden) openScopeMenu();
  }

  /* 排序菜单里的选中态 */
  function syncSortMenu() {
    for (const btn of el.sortMenu.querySelectorAll("button[data-sort]")) {
      btn.classList.toggle("on", btn.dataset.sort === state.sort);
    }
  }

  /** 点排序图标：菜单右边缘对齐按钮，换窗口宽度也不会错位。 */
  function toggleSortMenu() {
    const hidden = el.sortMenu.hidden;
    closeAll();
    const btn = $("btnSort").getBoundingClientRect();
    el.sortMenu.style.right = Math.round(window.innerWidth - btn.right) + "px";
    el.sortMenu.hidden = !hidden;
    syncSortMenu();
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
    // 视图切换：主页 / 分类
    el.viewSwitch.addEventListener("click", (e) => {
      const btn = e.target.closest(".vs-btn");
      if (!btn || btn.disabled) return;
      if (btn.dataset.view === "categories") {
        ctx.setView("categories");
        ctx.refreshShelves();
      } else {
        ctx.setView("home");
      }
    });
    $("scopePick").onclick = () => toggleScopeMenu();
    $("scopeClear").onclick = () => {
      el.scopeMenu.hidden = true;
      setScope("all");
      ctx.toast("已显示全部游戏");
    };
    el.scopeMenu.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-scope-type]");
      if (!btn) return;
      el.scopeMenu.hidden = true;
      setScope(btn.dataset.scopeType, btn.dataset.scopeValue || "");
    });

    // 搜索过滤
    el.search.oninput = (e) => {
      state.filter = e.target.value;
      el.searchClear.hidden = !state.filter;
      if (el.catQuery.value !== state.filter) el.catQuery.value = state.filter;   // 两处搜索同步
      ctx.renderHall();
    };
    el.searchClear.onclick = () => {
      el.search.value = ""; state.filter = ""; el.searchClear.hidden = true;
      ctx.renderHall();
    };
    el.search.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const first = visibleGames()[0];
        if (first) { ctx.setFocus(first.id); ctx.openGame(first.id); }
      }
    });

    // 排序（工具条图标 → 菜单）
    $("btnSort").onclick = () => toggleSortMenu();
    el.sortMenu.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-sort]");
      if (!btn) return;
      state.sort = btn.dataset.sort;
      el.sortMenu.hidden = true;
      ctx.renderHall();
      const game = ctx.currentGame();
      if (game) ctx.setFocus(game.id);
    });
  }

  return { syncScopePill, setScope, renderScopeMenu, openScopeMenu, toggleScopeMenu,
           syncSortMenu, toggleSortMenu, bind };
}
