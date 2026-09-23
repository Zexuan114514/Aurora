/**
 * Aurora v2 · 入口
 *
 * 样式顺序由 `@/styles/app.css` 负责（组件库 → 令牌 → 主题 → 布局 → 桥接）。
 * 组件按需注册（见 `@/core/element`），不再整库安装。
 */
import "@/styles/app.css"

import { createApp } from "vue"

import App from "@/App.vue"
import { bridge, call, recordError } from "@/core/api"
import { refreshLibrary, startLiveTicker } from "@/core/actions"
import { closeGame, closeSettings, runtime, setView } from "@/core/app"
import { installElement } from "@/core/element"
import { bindShell } from "@/core/shell"
import { ADD_KEY, state, toast } from "@/core/store"
import { installSurface } from "@/core/surface"
import { bindWindowControls } from "@/core/window"
import { watchSystemMode } from "@/core/theme"

const app = createApp(App)
installElement(app)
app.mount("#app")

installSurface({
  ring: () => runtime.ring?.readout() || { float: 0, target: 0, drag: false, focus: state.focus, keys: [] },
  layout: () => runtime.ring?.layoutReadout() || {
    name: "unknown", flatClass: false, rowTransform: "", viewportWidth: 0, tiles: [],
  },
})

bindWindowControls(() => runtime.ring?.endDrag())
bindShell({
  ringKey: (event) => !!runtime.ring?.handleKey(event),
  closeSettings,
  setView,
  closeGame,
})

let booted = false

async function boot(): Promise<void> {
  if (booted) return
  booted = true
  try {
    await refreshLibrary()
  } catch (error) {
    recordError("初始化", error)
    toast("初始化失败：" + (error as Error).message, 6000)
  }
  watchSystemMode(state.settings)

  // 作用域：恢复上次看的分类 / 状态 / 厂商（分类被删掉就退回全部）
  try {
    const raw = localStorage.getItem("aurora.scope")
    const saved = raw ? JSON.parse(raw) : null
    const usable = saved && saved.type && saved.type !== "all"
      && (saved.type !== "shelf" || state.shelves.some((row) => row.id === saved.value))
    if (usable) state.scope = { type: saved.type, value: saved.value || "" }
  } catch { /* ignore */ }

  // 焦点：优先恢复上次看的那一款，否则用最近玩过的
  let want: string | null = null
  try { want = localStorage.getItem("aurora.focus") } catch { /* ignore */ }
  const has = (id: string | null) => !!id && state.games.some((game) => game.id === id)
  if (!has(want)) {
    const recent = state.games.slice().sort((a, b) => (b.last_played || 0) - (a.last_played || 0))
    want = recent[0]?.id || null
  }
  state.focus = has(want) ? want : (state.games[0]?.id || ADD_KEY)
  runtime.ring?.applyLayout()
  startLiveTicker()

  window.setInterval(async () => {
    try {
      const res = await call("refresh_running")
      const running = new Set<string>(res.running || [])
      for (const game of state.games) game.running = running.has(game.id)
    } catch { /* 桥接忙时忽略 */ }
  }, 7000)
}

function bridgeReady(): boolean {
  // 走 core/api 的 bridge()：桥接对象只在那一个模块里取（分层守卫盯这条）。
  const api = bridge()
  return !!(api && typeof api.bootstrap === "function")
}

function whenReady(): void {
  if (bridgeReady()) { void boot(); return }
  let tries = 0
  const timer = window.setInterval(() => {
    if (bridgeReady()) {
      window.clearInterval(timer)
      void boot()
    } else if (++tries > 300) {
      window.clearInterval(timer)
      const boot = document.getElementById("boot")
      if (boot) {
        boot.innerHTML = '<div style="text-align:center;color:#8b8b95;font-size:13px;line-height:1.7">'
          + "无法连接到本地服务，请重新启动 Aurora</div>"
      }
      recordError("桥接", new Error("bridge timeout"))
    }
  }, 50)
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", whenReady)
} else {
  whenReady()
}
