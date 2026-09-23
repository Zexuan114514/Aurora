/**
 * Aurora v2 · 游戏动作（导入 / 整库刷新 / 启动结束 / 批量任务 / 秒表）
 * 与 v1 core/actions.js 的行为一致，返回值与提示文案保持不变。
 */
import { call } from "@/core/api"
import { emitUi } from "@/core/bus"
import { ADD_KEY, currentGame, replaceGames, state, toast } from "@/core/store"
import { applyTheme } from "@/core/theme"

/** 把设置回填到界面（主题 / 外观），并通知各视图重绘。 */
function applySettings(settings: Record<string, any>): void {
  state.settings = { ...state.settings, ...settings }
  applyTheme(state.settings)
  emitUi("settings:applied")
}

/** 整库刷新：后端 bootstrap 是唯一来源，前端只做回填与重绘。 */
export async function refreshLibrary(): Promise<void> {
  const data = await call("bootstrap")
  replaceGames(data.games || [])
  state.sources = data.sources || []
  state.version = data.version || ""
  applySettings(data.settings || {})
  if (state.focus && state.focus !== ADD_KEY && !currentGame()) {
    state.focus = state.games[0]?.id || ADD_KEY
  }
  emitUi("library:loaded", data)
  emitUi("render")
}

export async function importGames(): Promise<void> {
  try {
    const res = await call("pick_executable")
    if (!res || res.cancelled) return
    if (!res.ok) { toast("导入失败：" + (res.error || "未知错误")); return }
    const games = res.games || []
    if (!games.length) return
    await refreshLibrary()
    emitUi("focus", games[games.length - 1].id)
    emitUi("close-game")
    toast(`已导入 ${games.length} 个游戏`)
  } catch (error) {
    toast("导入失败：" + (error as Error).message)
  }
}

/** 「开始游戏 / 结束游戏」：结束走 stop，启动失败要说清楚是哪一种失败。 */
export async function togglePlay(): Promise<void> {
  const game = currentGame()
  if (!game) return
  if (game.running) {
    await call("stop", game.id)
    toast("已结束游戏进程")
    return
  }
  const res = await call("launch", game.id)
  if (!res || !res.ok) {
    const map: Record<string, string> = {
      "missing-exe": "找不到可执行文件，可能已被移动或删除。",
      "already-running": "游戏已在运行中。",
    }
    toast(map[res && res.error] || "启动失败：" + ((res && res.error) || "未知错误"))
    return
  }
  toast("游戏已启动")
  const target = state.games.find((row) => row.id === game.id)
  if (target) target.running = true
  emitUi("render")
}

export async function startRefreshAll(): Promise<void> {
  if (state.batch) { toast("已经有一个批量任务在跑"); return }
  state.batch = { kind: "refresh", done: 0, total: 0 }
  const res = await call("refresh_all_metadata")
  if (!res || !res.ok) {
    state.batch = null
    toast(res && res.error === "empty" ? "库里还没有游戏" : "启动失败，请稍后再试")
    return
  }
  state.batch.total = res.total
  emitUi("batch", { kind: "refresh", done: 0, total: res.total })
  toast(`开始重新抓取 ${res.total} 个游戏的资料`)
}

export async function startTranslateAll(): Promise<void> {
  if (state.batch) { toast("已经有一个批量任务在跑"); return }
  state.batch = { kind: "translate", done: 0, total: 0 }
  const res = await call("translate_all_descriptions")
  if (!res || !res.ok) {
    state.batch = null
    toast(res && res.error === "empty" ? "库里还没有游戏" : "启动失败，请稍后再试")
    return
  }
  state.batch.total = res.total
  emitUi("batch", { kind: "translate", done: 0, total: res.total })
  toast(`开始翻译 ${res.total} 个游戏的简介`)
}

/** 运行中的秒表：每秒推一次 tick，界面自己按当前游戏算时长。 */
export function startLiveTicker(): void {
  if ((startLiveTicker as any)._timer) return
  ;(startLiveTicker as any)._timer = window.setInterval(() => {
    const game = currentGame()
    if (game?.running) emitUi("tick")
  }, 1000)
}

export { applySettings }
