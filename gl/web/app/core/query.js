/* Aurora 前端 · 筛选 / 排序 / 作用域（P4.3-q）
 *
 * 从主模块搬出来的查询逻辑。主页（大厅）与分类工作区共用同一份，
 * 所以「两处搜索与排序结果永远一致」这件事只在这里维持。
 *
 * 全是纯读：只读 store 里的 state，不改任何东西（改作用域在 views/toolbar.js）。
 */
import { state } from "./store.js";

export const STATUS_LABEL = { "": "未标记", playing: "在玩", cleared: "通关", shelved: "搁置" };
export const STATUS_GLYPH = { playing: "玩", cleared: "通", shelved: "搁" };
export const STATUS_ORDER = ["playing", "cleared", "shelved", ""];

/** 搜索命中：名字 / 各语言名 / 文件名 / 目录 / 开发商 / 类型等拼起来找子串。 */
export function searchHit(game, q) {
  return [game.name, game.steam_name, game.name_cn, game.name_original, game.exe_name,
          game.dir, (game.developers || []).join(" "), (game.publishers || []).join(" "),
          (game.genres || []).join(" "), (game.categories || []).join(" ")]
    .join(" ").toLowerCase().includes(q);
}

/** 按当前排序方式就地排序（返回同一个数组，调用方直接接着用）。 */
export function sortGames(list) {
  if (state.sort === "favorite") {
    list.sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0));
  } else if (state.sort === "name") list.sort((a, b) => a.name.localeCompare(b.name, "zh"));
  else if (state.sort === "recent") list.sort((a, b) => (b.last_played || 0) - (a.last_played || 0));
  else if (state.sort === "playtime") list.sort((a, b) => (b.play_time || 0) - (a.play_time || 0));
  return list;
}

/** 这个游戏在不在当前作用域里（分类 / 未分类 / 收藏 / 状态 / 开发商）。 */
export function inScope(game) {
  const scope = state.scope;
  if (scope.type === "shelf") return (game.bookshelf_ids || []).includes(scope.value);
  if (scope.type === "unfiled") return !(game.bookshelf_ids || []).length;
  if (scope.type === "fav") return !!game.favorite;
  if (scope.type === "status") return (game.status || "") === scope.value;
  if (scope.type === "dev") return (game.developers || []).includes(scope.value);
  return true;
}

/** 作用域的显示名（作用域胶囊与分类标题都用它）。 */
export function scopeName(scope = state.scope) {
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

export const scopeCount = () => state.games.filter(inScope).length;

/** 当前该显示哪些游戏：作用域 → 搜索 → 排序。 */
export function visibleGames() {
  let list = state.games.filter(inScope);
  const q = state.filter.trim().toLowerCase();
  if (q) list = list.filter((g) => searchHit(g, q));
  return sortGames(list);
}
