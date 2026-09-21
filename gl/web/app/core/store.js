/* Aurora 前端 · 单一状态与实体更新（P4.2）
 *
 * 约定：**实体（games / shelves / settings / 选中态…）只在 store 里改**，
 * 视图与事件处理不许自己拼 `state.games[idx] = {...}`。这样「谁改了数据」永远
 * 只有一个入口，后面拆 views/ 时也不会出现两边各改一半的情况。
 *
 * `state` 用 export const 导出的是**活绑定**：模块内对它属性的修改，导入方
 * 立刻能看到（视图直接读 `state.x` 也是允许的，只是不许直接写实体字段）。
 */

export const state = {
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

/* 「＋ 导入游戏」那一格的占位键：大厅环上它也算一格，主模块与各视图共用。 */
export const ADD_KEY = "__add__";

/** 按 id 找一个游戏（找不到返回 undefined）。 */
export const findGame = (id) => state.games.find((g) => g.id === id);

/** 当前焦点游戏。 */
export const currentGame = () => findGame(state.focus);

/** 忙标记：后端在搜元数据 / 批量处理时按钮要转圈。 */
export const setBusy = (id, on = true) => {
  if (!id) return;
  if (on) state.busy[id] = true;
  else delete state.busy[id];
};

/** 新增或合并一个游戏（事件推送来的实体统一走这里）。返回是否是新加的。 */
export const upsertGame = (game, extra = {}) => {
  if (!game || !game.id) return false;
  const index = state.games.findIndex((g) => g.id === game.id);
  if (index < 0) {
    state.games.push({ ...game, ...extra });
    return true;
  }
  state.games[index] = { ...state.games[index], ...game, ...extra };
  return false;
};

/** 把整个实体推进库（导入回执用，调用方已经保证是新的）。 */
export const pushGame = (game) => {
  if (!game || !game.id) return false;
  if (findGame(game.id)) return false;
  state.games.push(game);
  return true;
};

/** 局部更新一个游戏实体（就地合并，保留引用）。 */
export const patchGame = (id, fields) => {
  const game = findGame(id);
  if (!game) return undefined;
  Object.assign(game, fields || {});
  return game;
};

/** 整库替换（refreshLibrary 用）。 */
export const replaceGames = (games) => {
  state.games = Array.isArray(games) ? games : [];
  return state.games;
};

/** 整表替换分类书架。 */
export const replaceShelves = (shelves) => {
  state.shelves = Array.isArray(shelves) ? shelves : [];
  return state.shelves;
};
