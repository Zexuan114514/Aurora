/* Aurora 前端 · 分类视图（P4.3-b）
 *
 * 书架 / 多选 / 游戏状态这一段。视图只依赖 core（api / dom / store），
 * 需要主模块的渲染与提示函数时由 `createCategoriesView(ctx)` 注入 —— 这样
 * 视图永远不用反向 import 主模块，也就不会有循环依赖。
 */
import { call } from "../core/api.js";
import { el } from "../core/dom.js";
import { state } from "../core/store.js";

export function createCategoriesView(ctx) {
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
      ctx.renderCatBar();
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
      ctx.applyShelfPayload(res);
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
      ctx.applyShelfPayload(res);
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
      ctx.applyShelfPayload(await call("delete_shelf", id));
      if (state.scope.type === "shelf" && state.scope.value === id) ctx.setScope("all");
      ctx.toast("已删除分类");
    }

    async function assignSelected(target) {
      const ids = [...state.selected];
      if (!ids.length) { ctx.toast("先勾选几张封面"); return; }
      if (!target) { ctx.toast("先在下拉里选一个目标分类"); return; }
      const res = await call("add_games_to_shelf", ids, [target]);
      state.selected.clear();
      ctx.applyShelfPayload(res);
      const shelf = state.shelves.find((s) => s.id === target);
      ctx.toast(`已把 ${res.count || 0} 部加入「${shelf ? shelf.name : "分类"}」`);
    }

    async function removeSelectedFromScope() {
      const ids = [...state.selected];
      if (state.scope.type !== "shelf" || !ids.length) return;
      const res = await call("remove_games_from_shelf", ids, state.scope.value);
      state.selected.clear();
      ctx.applyShelfPayload(res);
      ctx.toast(`已移出 ${res.count || 0} 部`);
    }

    async function favoriteSelected(value) {
      const ids = [...state.selected];
      if (!ids.length) { ctx.toast("先勾选几张封面"); return; }
      const res = await call("set_games_favorite", ids, value);
      ctx.toast(value ? `已收藏 ${res.count || 0} 部` : `已取消收藏 ${res.count || 0} 部`);
      ctx.applyShelfPayload(res);
    }

    async function setGameStatus(gameId, status) {
      const res = await call("set_game_status", gameId, status);
      if (!res || !res.ok) { ctx.toast("保存状态失败"); return; }
      const game = state.games.find((g) => g.id === gameId);
      if (game && res.game) Object.assign(game, res.game);
      ctx.render();
      ctx.renderDetail();
      ctx.toast(status ? `已标记为「${ctx.STATUS_LABEL[status]}」` : "已清除状态标记");
    }

  return {setOrganizing, togglePick, createShelf, renameShelfFlow, deleteShelfFlow, assignSelected, removeSelectedFromScope, favoriteSelected, setGameStatus
  };
}
