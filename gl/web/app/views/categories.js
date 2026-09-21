/* Aurora 前端 · 分类工作区（P4.3-b 动作，P4.3-v 整块收口）
 *
 * 分类屏的**全部**内容都在这里：左栏（范围 / 自定义分类 / 状态 / 开发商）、
 * 标题与批量操作条、封面墙、多选与归类动作，以及这些控件的事件绑定。
 *
 * 视图只依赖 core；主模块与其它视图的口子由 `createCategoriesView(ctx)` 注入：
 *   render / renderHall    主模块重绘
 *   setScope / syncSortMenu 工具条（views/toolbar.js）
 *   renderDetail / setFocus / openPanel 游戏页与焦点
 *   toast / modal / cssEscape / coverSources 提示与工具
 */
import { call } from "../core/api.js";
import { $, el, esc, imgHtml } from "../core/dom.js";
import { state, replaceShelves } from "../core/store.js";
import { STATUS_LABEL, STATUS_ORDER, inScope, scopeCount, scopeName,
         searchHit, sortGames } from "../core/query.js";

const DEV_LIMIT = 12;

export function createCategoriesView(ctx) {
  /* ------------------------------------------------------------ 渲染 */
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
        <span class="cat-art">${imgHtml("", ctx.coverSources(game))}
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
    if (Array.isArray(res.shelves)) replaceShelves(res.shelves);
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
    ctx.render();
  }

  async function refreshShelves() {
    try {
      applyShelfPayload(await call("list_shelves"));
    } catch (_) { /* 离线时保留现有状态 */ }
  }

  /* ------------------------------------------------------------ 动作 */
  function setOrganizing(on) {
    state.organizing = !!on;
    if (!state.organizing) state.selected.clear();
    ctx.render();
  }

  function togglePick(gameId) {
    if (state.selected.has(gameId)) state.selected.delete(gameId);
    else state.selected.add(gameId);
    // 只改这一张卡片的勾选态：整墙重绘会让连点丢事件、也会闪
    const card = el.catWall.querySelector(`.cat-card[data-id="${ctx.cssEscape(gameId)}"]`);
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
    ctx.toast(`已新建分类「${res.shelf.name}」`);
    return res.shelf;
  }

  async function renameShelfFlow(id) {
    const shelf = state.shelves.find((s) => s.id === id);
    if (!shelf) return;
    const value = await ctx.modal({
      title: "重命名分类", body: "只改分类名字，不动里面的游戏。",
      input: true, value: shelf.name, okText: "保存",
    });
    if (value === null) return;
    const res = await call("rename_shelf", id, value);
    if (!res || !res.ok) {
      ctx.toast(res && res.error === "duplicate" ? "已经有同名的分类了" : "名字不能为空");
      return;
    }
    applyShelfPayload(res);
    ctx.toast("已重命名分类");
  }

  async function deleteShelfFlow(id) {
    const shelf = state.shelves.find((s) => s.id === id);
    if (!shelf) return;
    const ok = await ctx.modal({
      title: "删除分类",
      body: `删除「${shelf.name}」？游戏和游玩记录都不会动，只是不再归在这个分类里。`,
      okText: "删除",
    });
    if (!ok) return;
    applyShelfPayload(await call("delete_shelf", id));
    if (state.scope.type === "shelf" && state.scope.value === id) ctx.setScope("all");
    ctx.toast("已删除分类");
  }

  /** 分类排序：↑ / ↓ 各挪一格（以前这里漏了实现，点了会报 ReferenceError）。 */
  async function moveShelf(id, delta) {
    const res = await call("move_shelf", id, Number(delta));
    if (!res || !res.ok) return;
    applyShelfPayload(res);
  }

  async function assignSelected(target) {
    const ids = [...state.selected];
    if (!ids.length) { ctx.toast("先勾选几张封面"); return; }
    if (!target) { ctx.toast("先在下拉里选一个目标分类"); return; }
    const res = await call("add_games_to_shelf", ids, [target]);
    state.selected.clear();
    applyShelfPayload(res);
    const shelf = state.shelves.find((s) => s.id === target);
    ctx.toast(`已把 ${res.count || 0} 部加入「${shelf ? shelf.name : "分类"}」`);
  }

  async function removeSelectedFromScope() {
    const ids = [...state.selected];
    if (state.scope.type !== "shelf" || !ids.length) return;
    const res = await call("remove_games_from_shelf", ids, state.scope.value);
    state.selected.clear();
    applyShelfPayload(res);
    ctx.toast(`已移出 ${res.count || 0} 部`);
  }

  async function favoriteSelected(value) {
    const ids = [...state.selected];
    if (!ids.length) { ctx.toast("先勾选几张封面"); return; }
    const res = await call("set_games_favorite", ids, value);
    ctx.toast(value ? `已收藏 ${res.count || 0} 部` : `已取消收藏 ${res.count || 0} 部`);
    applyShelfPayload(res);
  }

  async function setGameStatus(gameId, status) {
    const res = await call("set_game_status", gameId, status);
    if (!res || !res.ok) { ctx.toast("保存状态失败"); return; }
    const game = state.games.find((g) => g.id === gameId);
    if (game && res.game) Object.assign(game, res.game);
    ctx.render();
    ctx.renderDetail();
    ctx.toast(status ? `已标记为「${STATUS_LABEL[status]}」` : "已清除状态标记");
  }

  /* ------------------------------------------------------------ 事件绑定 */
  function bind() {
    // 分类工作区（事件委托，界面重绘后依然有效）
    el.categoriesView.addEventListener("click", async (e) => {
      const scopeBtn = e.target.closest("[data-scope]");
      if (scopeBtn) {
        ctx.setScope(scopeBtn.dataset.scope, scopeBtn.dataset.id || "");
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
          ctx.setFocus(id);
          ctx.renderDetail();
          ctx.openPanel(el.detailPanel);
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
      if (shelf) ctx.setScope("shelf", shelf.id);
    });

    // 分类工作区与主页共用同一份搜索 / 排序
    el.catQuery.addEventListener("input", (e) => {
      state.filter = e.target.value;
      el.search.value = state.filter;
      el.searchClear.hidden = !state.filter;
      ctx.renderHall();
      renderCatHead();
      renderCatWall();
    });
    el.catSort.onchange = (e) => {
      state.sort = e.target.value;
      ctx.syncSortMenu();
      ctx.renderHall();
      renderCatHead();
      renderCatWall();
    };
  }

  return {
    bind, renderCategories, renderCatBar, renderCatHead, renderCatWall,
    renderCatDevs, applyShelfPayload, refreshShelves, catList,
    setOrganizing, togglePick, createShelf, renameShelfFlow, deleteShelfFlow,
    moveShelf, assignSelected, removeSelectedFromScope, favoriteSelected, setGameStatus,
  };
}
