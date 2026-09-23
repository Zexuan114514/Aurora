/**
 * Aurora v2 · 窗口拖拽 / 缩放 / 标题栏按钮（v1 core/window.js 迁移）
 * 无边框窗口的拖动、四周缩放、最小化 / 最大化 / 关闭，以及鼠标在窗口外松开时的清理。
 */
import { call } from "@/core/api"

export function bindWindowControls(onPointerReset: () => void): void {
  let drag: { sx: number; sy: number; queued: boolean } | null = null
  let resize: { edge: string; sx: number; sy: number; base: any; queued: boolean } | null = null

  const on = (id: string, fn: () => void) => {
    const node = document.getElementById(id)
    if (node) node.onclick = fn
  }
  on("btnMin", () => call("window_cmd", "minimize"))
  on("btnMax", () => call("window_cmd", "toggle_maximize"))
  on("btnClose", () => call("window_cmd", "close"))

  document.addEventListener("mousedown", async (event) => {
    if (event.button !== 0) return
    const target = event.target as HTMLElement
    const rz = target.closest(".rz") as HTMLElement | null
    if (rz) {
      event.preventDefault()
      resize = { edge: rz.dataset.edge || "", sx: event.screenX, sy: event.screenY, base: null, queued: false }
      resize.base = await call("resize_start")
      return
    }
    const handle = target.closest("[data-drag]")
    if (!handle) return
    if (target.closest("[data-nodrag],button,input,select,textarea,a,.gi,.bg-item,.match-item")) return
    event.preventDefault()
    drag = { sx: event.screenX, sy: event.screenY, queued: false }
    await call("drag_start")
  })

  document.addEventListener("mousemove", (event) => {
    if (resize && resize.base) {
      if (resize.queued) return
      resize.queued = true
      const { screenX, screenY } = event
      requestAnimationFrame(() => {
        if (!resize || !resize.base) return
        resize.queued = false
        const dpr = window.devicePixelRatio || 1
        const dx = (screenX - resize.sx) * dpr
        const dy = (screenY - resize.sy) * dpr
        const base = resize.base
        let { x, y, w, h } = base
        if (resize.edge.includes("e")) w = base.w + dx
        if (resize.edge.includes("s")) h = base.h + dy
        if (resize.edge.includes("w")) { w = base.w - dx; x = base.x + dx }
        if (resize.edge.includes("n")) { h = base.h - dy; y = base.y + dy }
        call("resize_apply", Math.round(x), Math.round(y), Math.round(w), Math.round(h), resize.edge)
      })
      return
    }
    if (drag) {
      if (drag.queued) return
      drag.queued = true
      const dx = event.screenX - drag.sx
      const dy = event.screenY - drag.sy
      requestAnimationFrame(() => {
        if (drag) call("drag_move", dx * (window.devicePixelRatio || 1), dy * (window.devicePixelRatio || 1))
        if (drag) drag.queued = false
      })
    }
  })

  function dropPointerState() {
    if (drag) { drag = null; call("drag_end") }
    if (resize) resize = null
    onPointerReset()
  }
  document.addEventListener("mouseup", dropPointerState)
  window.addEventListener("blur", dropPointerState)

  document.addEventListener("dblclick", (event) => {
    const target = event.target as HTMLElement
    if (target.closest("[data-drag]") && !target.closest("[data-nodrag],button,input,select,a,.gi")) {
      call("window_cmd", "toggle_maximize")
    }
  })
}
