/** Aurora v2 · 筛选 / 排序 / 作用域（v1 core/query.js 原样迁移，主页与分类共用）。 */
import { state } from "@/core/store"
import type { Game, Scope } from "@/core/types"

export const STATUS_LABEL: Record<string, string> = {
  "": "未标记", playing: "在玩", cleared: "通关", shelved: "搁置",
}
export const STATUS_GLYPH: Record<string, string> = {
  playing: "玩", cleared: "通", shelved: "搁",
}
export const STATUS_ORDER = ["playing", "cleared", "shelved", ""]

/** 搜索命中：名字 / 各语言名 / 文件名 / 目录 / 开发商 / 类型等拼起来找子串。 */
export function searchHit(game: Game, q: string): boolean {
  return [
    game.name, game.steam_name, game.name_cn, game.name_original, game.exe_name,
    game.dir, (game.developers || []).join(" "), (game.publishers || []).join(" "),
    (game.genres || []).join(" "), (game.categories || []).join(" "),
  ].join(" ").toLowerCase().includes(q)
}

/** 按当前排序方式就地排序（返回同一个数组）。 */
export function sortGames<T extends Game>(list: T[]): T[] {
  if (state.sort === "favorite") {
    list.sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0))
  } else if (state.sort === "name") {
    list.sort((a, b) => String(a.name).localeCompare(String(b.name), "zh"))
  } else if (state.sort === "recent") {
    list.sort((a, b) => (b.last_played || 0) - (a.last_played || 0))
  } else if (state.sort === "playtime") {
    list.sort((a, b) => (b.play_time || 0) - (a.play_time || 0))
  }
  return list
}

/** 这个游戏在不在当前作用域里（分类 / 未分类 / 收藏 / 状态 / 开发商）。 */
export function inScope(game: Game, scope: Scope = state.scope): boolean {
  if (scope.type === "shelf") return (game.bookshelf_ids || []).includes(scope.value)
  if (scope.type === "unfiled") return !(game.bookshelf_ids || []).length
  if (scope.type === "fav") return !!game.favorite
  if (scope.type === "status") return (game.status || "") === scope.value
  if (scope.type === "dev") return (game.developers || []).includes(scope.value)
  return true
}

/** 作用域的显示名（作用域胶囊与分类标题都用它）。 */
export function scopeName(scope: Scope = state.scope): string {
  if (scope.type === "shelf") {
    const shelf = state.shelves.find((row) => row.id === scope.value)
    return shelf ? shelf.name : "分类"
  }
  if (scope.type === "unfiled") return "未分类"
  if (scope.type === "fav") return "已收藏"
  if (scope.type === "status") return STATUS_LABEL[scope.value] ?? "状态"
  if (scope.type === "dev") return scope.value
  return "全部游戏"
}

export const scopeCount = (): number => state.games.filter((g) => inScope(g)).length

/** 当前该显示哪些游戏：作用域 → 搜索 → 排序。 */
export function visibleGames(): Game[] {
  let list = state.games.filter((game) => inScope(game))
  const q = state.filter.trim().toLowerCase()
  if (q) list = list.filter((game) => searchHit(game, q))
  return sortGames(list)
}
