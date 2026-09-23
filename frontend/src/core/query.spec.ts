import { beforeEach, describe, expect, it } from "vitest"

import { inScope, scopeName, searchHit, sortGames, visibleGames } from "@/core/query"
import { state } from "@/core/store"

const game = (over: Record<string, unknown> = {}) => ({
  id: String(over.id || Math.random()),
  name: String(over.name || "ゲーム"),
  exe_name: String(over.exe_name || "game.exe"),
  developers: (over.developers as string[]) || ["メーカー"],
  genres: (over.genres as string[]) || ["冒险"],
  bookshelf_ids: (over.bookshelf_ids as string[]) || [],
  ...over,
}) as any

describe("筛选 / 排序 / 作用域", () => {
  beforeEach(() => {
    state.games = []
    state.shelves = []
    state.filter = ""
    state.sort = "default"
    state.scope = { type: "all", value: "" }
  })

  it("默认排序保持原始顺序", () => {
    const list = [game({ name: "B" }), game({ name: "A" })]
    expect(sortGames(list.slice()).map((g) => g.name)).toEqual(["B", "A"])
  })

  it("按名称排序用中文排序规则", () => {
    state.sort = "name"
    const source = [game({ name: "乙" }), game({ name: "甲" }), game({ name: "A" })]
    const names = sortGames(source.slice()).map((g) => g.name)
    expect(names).toHaveLength(3)
    // 按 localeCompare(…, "zh") 的升序（具体次序由 ICU 决定，不写死）
    const expected = [...names].sort((a, b) => a.localeCompare(b, "zh"))
    expect(names).toEqual(expected)
  })

  it("收藏优先 / 最近游玩 / 游玩时长", () => {
    state.sort = "favorite"
    expect(sortGames([game({ favorite: false }), game({ favorite: true })])[0].favorite).toBe(true)

    state.sort = "recent"
    expect(sortGames([game({ last_played: 1 }), game({ last_played: 9 })])[0].last_played).toBe(9)

    state.sort = "playtime"
    expect(sortGames([game({ play_time: 1 }), game({ play_time: 9 })])[0].play_time).toBe(9)
  })

  it("搜索命中名字 / 开发商 / 类型，大小写不敏感", () => {
    const row = game({ name: "GINKA", developers: ["Frontwing"], genres: ["悬疑"] })
    expect(searchHit(row, "ginka")).toBe(true)
    expect(searchHit(row, "frontwing")).toBe(true)
    expect(searchHit(row, "悬疑")).toBe(true)
    expect(searchHit(row, "没有这个词")).toBe(false)
  })

  it("作用域：全部 / 未分类 / 收藏 / 分类 / 状态 / 开发商", () => {
    const plain = game({ id: "1" })
    const shelved = game({ id: "2", bookshelf_ids: ["s1"] })
    const fav = game({ id: "3", favorite: true })
    const playing = game({ id: "4", status: "playing" })
    expect(inScope(plain, { type: "all", value: "" })).toBe(true)
    expect(inScope(plain, { type: "unfiled", value: "" })).toBe(true)
    expect(inScope(shelved, { type: "unfiled", value: "" })).toBe(false)
    expect(inScope(shelved, { type: "shelf", value: "s1" })).toBe(true)
    expect(inScope(fav, { type: "fav", value: "" })).toBe(true)
    expect(inScope(playing, { type: "status", value: "playing" })).toBe(true)
    expect(inScope(plain, { type: "dev", value: "メーカー" })).toBe(true)
  })

  it("作用域显示名：分类名来自 shelves，找不到就退回「分类」", () => {
    state.shelves = [{ id: "s1", name: "悬疑推理" }]
    expect(scopeName({ type: "shelf", value: "s1" })).toBe("悬疑推理")
    expect(scopeName({ type: "shelf", value: "gone" })).toBe("分类")
    expect(scopeName({ type: "unfiled", value: "" })).toBe("未分类")
    expect(scopeName({ type: "all", value: "" })).toBe("全部游戏")
  })

  it("visibleGames = 作用域 → 搜索 → 排序", () => {
    state.games = [
      game({ id: "1", name: "Alpha" }),
      game({ id: "2", name: "Beta" }),
      game({ id: "3", name: "Alpha 2" }),
    ]
    state.sort = "name"
    state.filter = "alpha"
    expect(visibleGames().map((g) => g.id)).toEqual(["1", "3"])
    state.filter = ""
    expect(visibleGames()).toHaveLength(3)
  })
})
