/**
 * Aurora v2 · 界面级动作（焦点 / 进游戏页 / 视图切换 / 设置页开合）
 *
 * 这些动作横跨多个视图，放在 core 里：视图之间不互相 import，
 * 需要「动一下别的界面」时统一走 core/bus 的内部信号。
 */
import { call } from "@/core/api"
import { emitUi } from "@/core/bus"
import { ADD_KEY, closeAllPanels, currentGame, state } from "@/core/store"
import { togglePlay } from "@/core/actions"
import { visibleGames } from "@/core/query"

/** 大厅这一帧该排的键列表：可见游戏 + 末尾的「＋ 导入游戏」。 */
export const hallKeys = (): string[] => [...visibleGames().map((game) => game.id), ADD_KEY]

/** 视图运行时（大厅挂载后注入；没挂载时是空壳，调用安全）。 */
export const runtime: {
  ring?: any
  background?: { scheduleBackground: () => void; applyKenBurns?: (on: boolean) => void }
} = {}

/** 焦点变化：窗口图标、游戏页、背景、localStorage 都跟着走。 */
export function setFocus(id: string, opts: { scroll?: boolean; persist?: boolean } = {}): void {
  if (!id || id === state.focus) {
    if (opts.scroll !== false && !runtime.ring?.dragging()) runtime.ring?.update()
    return
  }
  state.focus = id
  const game = currentGame()
  const wantIcon = game?.custom_icon ? game.id : ""
  if (state.iconFor !== wantIcon) {
    state.iconFor = wantIcon
    call("apply_window_icon", wantIcon).catch(() => {})
  }
  emitUi("render")
  if (opts.scroll !== false && !runtime.ring?.dragging()) runtime.ring?.update()
  runtime.background?.scheduleBackground()
  if (opts.persist !== false) {
    try { localStorage.setItem("aurora.focus", state.focus) } catch { /* ignore */ }
  }
}

/** 大厅「进游戏页」：id 省略 = 当前焦点。 */
export function enterGame(id?: string): void {
  if (id) {
    if (state.focus !== id) setFocus(id)
    openGame(id)
    return
  }
  openGame()
}

/** 「直接开玩」：大厅的启动按钮（#btnHallPlay）、或在游戏页按回车。
 *  2026-09-23 反馈第 18 条删掉了原来的「双击封面启动」—— 提示条写着、
 *  实际只有侧栏双击生效，反直觉。 */
export function playGame(id?: string): void {
  if (id) {
    setFocus(id)
    openGame(id)
  }
  void togglePlay()
}

/** 大厅 ↔ 游戏页。 */
export function openGame(id?: string): void {
  if (id) state.focus = id
  if (!currentGame()) return
  state.page = "game"
  closeAllPanels()
  emitUi("render")
  runtime.background?.scheduleBackground()
}

export function closeGame(): void {
  state.page = "hall"
  emitUi("render")
}

/** 主页 ↔ 分类工作区。 */
export function setView(view: "home" | "categories"): void {
  state.view = view === "categories" ? "categories" : "home"
  state.organizing = false
  state.selected.clear()
  if (state.settingsOpen) state.settingsOpen = false
  closeAllPanels()
  emitUi("render")
  if (state.view === "home") runtime.ring?.update()
}

export function openSettings(tab?: string): void {
  state.settingsOpen = true
  closeAllPanels()
  if (tab) state.settingsTab = tab
  emitUi("render")
  emitUi("settings:open")
}

export function closeSettings(): void {
  state.settingsOpen = false
  emitUi("render")
}
