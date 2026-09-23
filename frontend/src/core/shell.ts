/**
 * Aurora v2 · 全局外壳
 * 点空白收起菜单 / Esc 逐层退出 / 拦 F5 与 Ctrl+R / Ctrl+F 聚焦搜索 /
 * 右键策略 / 拖放提示层（真正的导入由 main.py 注册的 drop 监听完成）。
 */
import { state, closeAllPanels } from "@/core/store"
import { emitUi } from "@/core/bus"

export function bindShell(ctx: {
  ringKey: (event: KeyboardEvent) => boolean
  closeSettings: () => void
  setView: (view: "home" | "categories") => void
  closeGame: () => void
}): void {
  document.addEventListener("click", (event) => {
    const target = event.target as HTMLElement
    if (!target.closest("#moreMenu, #btnMore")) state.menus.more = false
    if (!target.closest("#sortMenu, #btnSort")) state.menus.sort = false
    if (!target.closest("#scopeMenu, #scopePill")) state.menus.scope = false
  })

  document.addEventListener("keydown", (event) => {
    const target = event.target as HTMLElement
    const tag = target?.tagName || ""
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag) || (target as any)?.isContentEditable
    if (event.key === "Escape") {
      const anyPanel = Object.values(state.panels).some(Boolean)
      const anyMenu = Object.values(state.menus).some(Boolean)
      if (anyPanel || anyMenu) { closeAllPanels(); return }
      if (state.settingsOpen) { ctx.closeSettings(); return }
      if (String(state.view) === "categories") { ctx.setView("home"); return }
      if (state.page === "game") { ctx.closeGame(); return }
    }
    if (event.key === "F5" || (event.ctrlKey && event.key.toLowerCase() === "r")) {
      event.preventDefault()
    }
    if (state.settingsOpen || String(state.view) === "categories") return
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
      event.preventDefault()
      const box = (state.view === "categories"
        ? document.getElementById("catQuery")
        : document.getElementById("searchInput")) as HTMLInputElement | null
      box?.focus()
      box?.select()
      return
    }
    if (typing || !(document.getElementById("modal") as HTMLElement)?.hidden) return
    ctx.ringKey(event)
  })

  document.addEventListener("contextmenu", (event) => {
    const target = event.target as HTMLElement
    if (!target.closest("input,textarea,[contenteditable]")) event.preventDefault()
  })

  const hasFiles = (event: DragEvent) => {
    const types = event.dataTransfer?.types || []
    return Array.prototype.indexOf.call(types, "Files") >= 0
  }
  let dragDepth = 0
  document.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return
    dragDepth += 1
    emitUi("drop-hint", true)
  })
  document.addEventListener("dragover", (event) => {
    if (hasFiles(event)) event.preventDefault()
  })
  document.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return
    dragDepth = Math.max(0, dragDepth - 1)
    if (!dragDepth) emitUi("drop-hint", false)
  })
  document.addEventListener("drop", (event) => {
    dragDepth = 0
    emitUi("drop-hint", false)
    event.preventDefault()
  })

  // 图片回退链：img[data-srcs] 里按顺序放备用地址，加载失败自动换下一个
  document.addEventListener("error", (event) => {
    const img = event.target as HTMLImageElement
    if (!img || img.tagName !== "IMG" || !img.dataset) return
    let chain: string[] = []
    try { chain = JSON.parse(img.dataset.srcs || "[]") } catch { chain = [] }
    if (chain.length) {
      img.dataset.srcs = JSON.stringify(chain.slice(1))
      img.src = chain[0]
      return
    }
    img.classList.add("img-broken")
    img.parentElement?.classList.add("img-broken")
    img.closest(".bg-item, .gi-cover")?.classList.add("img-broken")
  }, true)
}
