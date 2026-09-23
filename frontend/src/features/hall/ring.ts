/**
 * Aurora v2 · 环本体（运行期状态 + 帧循环 + 拖动 / 滚轮 / 快捷键）
 *
 * v1 的 createRing 是「自己建 DOM + 自己摆位」；v2 里节点由 Vue 的 v-for 渲染，
 * 这里只负责**摆位与输入**：拿到 hallRow / hallViewport 两个元素，按 keys 顺序
 * 给 row.children[i] 写 transform —— 几何计算仍是 geometry.ts 里那套逐字迁移的纯函数。
 */
import { state } from "@/core/store"
import {
  RING_BASE, RING_GEOMETRY, applyRingSize, clearRingStyles, layoutReadout,
  placeRingTile, ringGeometryOf, ringMod, ringSigned, updateFlatRow, type RingSize,
} from "@/features/hall/geometry"

export type HallLayout = "ring" | "flat" | "list"

export interface RingHooks {
  keys: () => string[]
  onFocus: (key: string, opts?: { scroll?: boolean; persist?: boolean }) => void
  onEnter: (id?: string) => void
  onPlay: (id?: string) => void
  /** 「＋ 导入游戏」那一格：直接进本地导入（原来弹二选一菜单，见 P8.6）。 */
  onAdd: () => void
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function createRing(hooks: RingHooks, addKey: string) {
  const RING = {
    ...RING_GEOMETRY,
    float: 0,
    target: 0,
    raf: 0,
    last: 0,
    ready: false,
    flatReady: false,
    dragActive: false,
    keysSig: "",
  }
  let row: HTMLElement | null = null
  let viewport: HTMLElement | null = null
  let size: RingSize = { unit: 1, w: 180, h: 270, rx: 580, rz: 260, depth: 1100 }
  let swipe: any = null
  let moved = false
  let wheelLast = 0

  const layout = (): HallLayout => {
    const value = String(state.settings.hall_layout || "list")
    return value === "ring" || value === "flat" ? value : "list"
  }
  const layoutName = () => layout()

  function attach(nextRow: HTMLElement, nextViewport: HTMLElement) {
    row = nextRow
    viewport = nextViewport
  }

  function measure() {
    if (!row || !viewport) return
    const vw = viewport.clientWidth || window.innerWidth || 1380
    const vh = viewport.clientHeight || Math.max(420, (window.innerHeight || 880) - 170)
    size = ringGeometryOf({
      viewportWidth: vw, viewportHeight: vh, geometry: RING_GEOMETRY, base: RING_BASE, clamp,
    })
    applyRingSize({ row, viewport, size })
  }

  function nodes(): HTMLElement[] {
    return row ? (Array.from(row.children) as HTMLElement[]) : []
  }

  function frame(ts: number) {
    const list = nodes()
    if (!list.length || layout() !== "ring") {
      RING.raf = 0
      return
    }
    if (!RING.last) RING.last = ts
    const dt = clamp((ts - RING.last) / 1000, 0.001, 0.05)
    RING.last = ts
    if (!RING.dragActive) {
      RING.float += (RING.target - RING.float) * (1 - Math.exp(-dt / RING.tau))
      if (Math.abs(RING.target - RING.float) < 0.002) RING.float = RING.target
    }
    list.forEach((node, index) => {
      placeRingTile(node, ringSigned(index - RING.float, list.length), { ring: RING, size })
    })
    if (RING.dragActive || Math.abs(RING.target - RING.float) > 0.0005) {
      RING.raf = requestAnimationFrame(frame)
    } else {
      RING.raf = 0
      RING.last = 0
    }
  }

  function run() {
    if (!RING.raf) {
      RING.last = 0
      RING.raf = requestAnimationFrame(frame)
    }
  }

  const indexOf = (key: string | null) => hooks.keys().indexOf(String(key))

  /** 让环转到当前焦点；instant 用于首帧、换筛选、窗口缩放这类不该有动画的场合。 */
  function update(instant = false) {
    if (!row || !viewport) return
    const keys = hooks.keys()
    if (layout() === "flat") {
      updateFlatRow({ row, viewport, keys, focus: state.focus, ring: RING, instant })
      return
    }
    if (layout() === "list") {
      for (const node of nodes()) clearRingStyles(node)
      RING.float = RING.target = Math.max(0, keys.indexOf(String(state.focus)))
      return
    }
    measure()
    const index = indexOf(state.focus)
    const n = nodes().length
    if (index < 0 || !n) return
    if (instant || !RING.ready) {
      RING.float = index
      RING.target = index
      RING.ready = true
    } else {
      RING.target = RING.float + ringSigned(index - RING.float, n)
    }
    run()
  }

  /** 布局切换：清掉另一套布局留下的内联样式再重新摆位。 */
  function applyLayout() {
    document.body.classList.toggle("hall-flat", layout() === "flat")
    if (layout() === "flat") {
      for (const node of nodes()) clearRingStyles(node)
      RING.flatReady = false
    } else {
      RING.ready = false
      RING.float = RING.target = Math.max(0, hooks.keys().indexOf(String(state.focus)))
    }
    update(true)
  }

  /** 方向键 / 滚轮：走到头就从另一侧绕回来（环形）；平铺与列表不循环。 */
  function move(delta: number) {
    const keys = hooks.keys()
    if (!keys.length || !delta) return
    const index = keys.indexOf(String(state.focus))
    const base = index < 0 ? 0 : index
    const next = layout() === "ring"
      ? ringMod(base + delta, keys.length)
      : Math.min(keys.length - 1, Math.max(0, base + delta))
    if (next !== index) hooks.onFocus(keys[next])
    else if (!RING.dragActive) update()
  }

  function jump(edge: "start" | "end") {
    const keys = hooks.keys()
    if (!keys.length) return
    hooks.onFocus(edge === "end" ? keys[keys.length - 1] : keys[0])
  }

  /** 大厅快捷键：← → / Home / End / Enter。返回是否消费了这次按键。 */
  function handleKey(e: KeyboardEvent): boolean {
    if (e.key === "ArrowLeft") { e.preventDefault(); move(-1); return true }
    if (e.key === "ArrowRight") { e.preventDefault(); move(1); return true }
    if (e.key === "Home") { e.preventDefault(); jump("start"); return true }
    if (e.key === "End") { e.preventDefault(); jump("end"); return true }
    if (e.key !== "Enter") return false
    e.preventDefault()
    if (state.page === "game") hooks.onPlay()
    else if (state.focus === addKey) {
      hooks.onAdd()
    } else hooks.onEnter()
    return true
  }

  /** 输入绑定：大厅挂载后调一次。 */
  function bind(app: HTMLElement) {
    if (!row || !viewport) return
    // 「悬停 320ms 即切到该游戏」按反馈第 19-b 条删掉了：它反直觉，而且挡住右键菜单
    // 的使用（鼠标一停就把焦点抢走）。滑动只保留滚轮 / ← → / 拖拽这些显式动作。
    row.addEventListener("click", (event) => {
      const tile = (event.target as HTMLElement).closest(".gi") as HTMLElement | null
      if (!tile || moved) return
      if (tile.dataset.add) { hooks.onAdd(); return }
      hooks.onEnter(tile.dataset.id)
    })
    const swipeStart = (event: MouseEvent) => {
      if (event.button !== 0) return
      moved = false
      if (state.settingsOpen || state.view === "categories") return
      const target = event.target as HTMLElement
      if (target.closest("a, input, select, textarea, .pill, [data-drag], .rz")) return
      if (target.closest("button") && !target.closest(".gi")) return
      swipe = {
        x: event.clientX, y: event.clientY, base: event.clientX,
        start: RING.float, active: false, flat: layout() === "flat", baseX: 0, dx: 0,
      }
    }
    const swipeMove = (event: MouseEvent) => {
      if (!swipe) return
      if (state.settingsOpen || state.view === "categories") { swipe = null; return }
      const dx = event.clientX - swipe.base
      const dy = event.clientY - swipe.y
      if (!swipe.active) {
        if (Math.abs(dx) < 7 || Math.abs(dx) <= Math.abs(dy)) return
        swipe.active = true
        moved = true
        RING.dragActive = true
        row?.classList.add("ring-drag")
      }
      const pos = swipe.start - dx / (RING.dragPx * size.unit)
      if (swipe.flat) {
        if (!swipe.baseX) {
          const match = /translate3d\((-?[\d.]+)px/.exec(row?.style.transform || "")
          swipe.baseX = match ? Number(match[1]) : 0
        }
        swipe.dx = dx
        if (row) {
          row.style.transition = "none"
          row.style.transform = `translate3d(${Math.round(swipe.baseX + dx)}px, 0, 0)`
        }
        return
      }
      if (layout() !== "ring") return
      RING.float = RING.target = pos
      run()
      const keys = hooks.keys()
      if (keys.length) {
        const near = keys[ringMod(Math.round(pos), keys.length)]
        if (near && near !== state.focus) hooks.onFocus(near, { scroll: false })
      }
    }
    const swipeEnd = () => {
      if (!swipe) return
      const { active, flat: wasFlat, dx: dragDx } = swipe
      swipe = null
      if (!active) return
      RING.dragActive = false
      row?.classList.remove("ring-drag")
      if (wasFlat) {
        const tile = (row?.querySelector(".gi") || row?.firstChild) as HTMLElement | null
        const step = (tile ? tile.getBoundingClientRect().width : 172) + 24
        const steps = Math.round(-(dragDx || 0) / Math.max(40, step))
        if (row) row.style.transition = ""
        if (steps) move(steps)
        update(true)
        return
      }
      RING.target = Math.round(RING.float)
      run()
      const keys = hooks.keys()
      if (keys.length) {
        const near = keys[ringMod(RING.target, keys.length)]
        if (near) hooks.onFocus(near, { scroll: false })
      }
    }
    app.addEventListener("mousedown", swipeStart, true)
    document.addEventListener("mousemove", swipeMove)
    document.addEventListener("mouseup", swipeEnd)
    window.addEventListener("blur", swipeEnd)

    app.addEventListener("wheel", (event) => {
      if (state.settingsOpen || state.view === "categories") return
      const target = event.target as HTMLElement
      if (target.closest(".sheet, .menu, .modal, input, select, textarea, #toolbar, #toast")) return
      if (!state.games.length) return
      event.preventDefault()
      const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
      const now = Date.now()
      if (now - wheelLast < 130) return
      if (Math.abs(delta) < 2) return
      wheelLast = now
      move(delta > 0 ? 1 : -1)
    }, { passive: false })
  }

  return {
    attach,
    bind,
    update,
    measure,
    applyLayout,
    move,
    jump,
    handleKey,
    endDrag: () => { if (swipe) swipe = null; RING.dragActive = false },
    dragging: () => RING.dragActive,
    layoutName,
    readout: () => ({
      float: Number(RING.float.toFixed(3)),
      target: RING.target,
      drag: RING.dragActive,
      focus: state.focus,
      keys: hooks.keys(),
    }),
    layoutReadout: () => layoutReadout({
      row: row as HTMLElement,
      viewport: (viewport as HTMLElement).getBoundingClientRect(),
      layoutName: layoutName(),
      flatClass: document.body.classList.contains("hall-flat"),
    }),
    RING,
  }
}
