/**
 * Aurora v2 · 单一状态源
 *
 * 与 v1 的约定一致：**实体只在 store 里改**，视图不许自己拼 `state.games[i] = …`。
 * v2 用 Vue 的 reactive 包一层，视图直接读 `state.x` 即可自动重绘。
 */
import { reactive } from "vue"

import { normalizeGame } from "@/core/assets"
import type { Game, Scope, Shelf } from "@/core/types"

/** 「＋ 导入游戏」那一格的占位键：大厅环上它也算一格。 */
export const ADD_KEY = "__add__"

export const state = reactive({
  games: [] as Game[],
  focus: null as string | null,
  page: "hall" as "hall" | "game",
  settingsOpen: false,
  settingsTab: "look",
  settings: {} as Record<string, any>,
  sources: [] as any[],
  filter: "",
  sort: "default",
  version: "",
  // 单测跑在 node 环境里，没有 window；这里给个安全默认值
  dpr: (typeof window !== "undefined" ? window.devicePixelRatio : 1) || 1,
  busy: {} as Record<string, boolean>,
  iconFor: null as string | null,
  steam: [] as any[],
  picked: new Set<string>(),
  batch: null as null | { kind: string; done: number; total: number },
  sites: [] as any[],
  view: "home" as "home" | "categories",
  scope: { type: "all", value: "" } as Scope,
  shelves: [] as Shelf[],
  shelfStats: { unfiled: 0, total: 0 },
  organizing: false,
  selected: new Set<string>(),
  devExpand: false,
  toast: { text: "", until: 0 },
  panels: {
    background: false,
    detail: false,
    match: false,
    source: false,
    cover: false,
    steam: false,
    locale: false,
    vntext: false,
    get: false,
  } as Record<string, boolean>,
  menus: { more: false, sort: false, scope: false, hall: false },
  fetching: false,
  vntext: {} as Record<string, any>,
  locale: {} as Record<string, any>,
})

/** 按 id 找一个游戏（找不到返回 undefined）。 */
export const findGame = (id?: string | null): Game | undefined =>
  id ? state.games.find((game) => game.id === id) : undefined

/** 当前焦点游戏。 */
export const currentGame = (): Game | undefined => findGame(state.focus)

/** 忙标记：后端在搜元数据 / 批量处理时按钮要转圈。 */
export const setBusy = (id: string, on = true): void => {
  if (!id) return
  if (on) state.busy[id] = true
  else delete state.busy[id]
}

/** 新增或合并一个游戏（事件推送来的实体统一走这里）。返回是否是新加的。 */
export const upsertGame = (game: Game, extra: Partial<Game> = {}): boolean => {
  if (!game || !game.id) return false
  const incoming = normalizeGame(game)
  const index = state.games.findIndex((row) => row.id === incoming.id)
  if (index < 0) {
    state.games.push({ ...incoming, ...extra } as Game)
    return true
  }
  state.games[index] = { ...state.games[index], ...incoming, ...extra }
  return false
}

/** 把整个实体推进库（导入回执用，调用方已经保证是新的）。 */
export const pushGame = (game: Game): boolean => {
  if (!game || !game.id || findGame(game.id)) return false
  state.games.push(normalizeGame(game))
  return true
}

/** 局部更新一个游戏实体（就地合并）。 */
export const patchGame = (id: string, fields: Partial<Game>): Game | undefined => {
  const game = findGame(id)
  if (!game) return undefined
  Object.assign(game, fields)
  return game
}

/** 整库替换（refreshLibrary 用）。 */
export const replaceGames = (games: Game[]): Game[] => {
  state.games = Array.isArray(games) ? games.map((game) => normalizeGame(game)) : []
  return state.games
}

/** 整表替换分类书架。 */
export const replaceShelves = (shelves: Shelf[]): Shelf[] => {
  state.shelves = Array.isArray(shelves) ? shelves : []
  return state.shelves
}

/** 打开 / 关闭一个浮层（面板用 `open` 类，菜单用 hidden —— 与探针判据一致）。 */
export const openPanel = (name: string): void => {
  closeAllPanels()
  state.panels[name] = true
}
export const closePanel = (name: string): void => {
  state.panels[name] = false
}
export const closeAllPanels = (): void => {
  for (const key of Object.keys(state.panels)) state.panels[key] = false
  state.menus.more = false
  state.menus.sort = false
  state.menus.scope = false
  state.menus.hall = false
}

let toastTimer: number | undefined
/** 一句提示，2.6 秒后自己消失（时长可传）。 */
export const toast = (text: string, ms = 2600): void => {
  state.toast.text = text
  state.toast.until = Date.now() + ms
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    if (Date.now() >= state.toast.until) state.toast.text = ""
  }, ms)
}
