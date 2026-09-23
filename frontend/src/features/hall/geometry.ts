/**
 * Aurora v2 · 大厅环的纯几何
 *
 * 从 v1 gl/web/app/views/hall.js 逐字迁移（P4.3-e/f/g/h/i 那一串）。
 * 这里刻意不 import 任何东西 —— 依赖全部由调用方传入，便于单测，
 * 也保证 tools/visual.py 的环形判据（0/347.0、±16/283.2、32/232.5）数值不变。
 */

/** 环的几何常量（基准窗口 1380×690 下的像素值）。 */
export const RING_GEOMETRY = {
  step: 16,        // 相邻两张封面绕竖轴的角度（度）
  rx: 580,         // 水平半径（基准窗口下的像素）
  rz: 260,         // 纵深半径
  depth: 1100,     // 透视距离
  span: 4.6,       // 可见的半边张数，再远就藏起来（绕到背面）
  shrink: 0.24,    // 每远一格额外缩小的比例（透视之外再补一点）
  y: 36,           // 整圈封面的重心（相对舞台中心下移，避开顶部工具条）
  tau: 0.13,       // 回弹时间常数（秒），越小越干脆
  dragPx: 112,     // 横向拖动多少像素换一张
} as const

/** 基准封面尺寸（unit=1 时）。 */
export const RING_BASE = { w: 180, h: 270 }

export interface RingSize {
  unit: number
  w: number
  h: number
  rx: number
  rz: number
  depth: number
}

/** 按视口算这一帧的环尺寸：窗口越窄，半径与封面一起收。 */
export function ringGeometryOf({
  viewportWidth,
  viewportHeight,
  geometry = RING_GEOMETRY,
  base = RING_BASE,
  clamp,
}: {
  viewportWidth?: number
  viewportHeight?: number
  geometry?: typeof RING_GEOMETRY
  base?: { w: number; h: number }
  clamp: (value: number, lo: number, hi: number) => number
}): RingSize {
  const vw = viewportWidth || 1380
  const vh = viewportHeight || 690
  const unit = clamp(Math.min(vw / 1380, vh / 690), 0.6, 1.3)
  return {
    unit,
    w: Math.round(base.w * unit),
    h: Math.round(base.h * unit),
    rx: geometry.rx * unit,
    rz: geometry.rz * unit,
    depth: geometry.depth * unit,
  }
}

/** 把一张封面放到环上的第 r 格（r = 相对当前位置的浮点格数）。 */
export function placeRingTile(
  node: HTMLElement,
  r: number,
  { ring, size }: { ring: typeof RING_GEOMETRY; size: RingSize },
): void {
  const a = Math.abs(r)
  if (a > ring.span) {
    if (node.dataset.ringHidden !== "1") {
      node.dataset.ringHidden = "1"
      node.style.visibility = "hidden"
      node.style.opacity = "0"
      node.style.pointerEvents = "none"
      node.style.willChange = ""
    }
    return
  }
  if (node.dataset.ringHidden === "1") {
    node.dataset.ringHidden = "0"
    node.style.visibility = ""
    node.style.pointerEvents = ""
    node.style.willChange = "transform, opacity"
  }
  const deg = r * ring.step
  const rad = (deg * Math.PI) / 180
  const z = Math.cos(rad) * size.rz
  const scale = 1 / (1 + ring.shrink * a)
  const x = Math.sin(rad) * size.rx
  const y = ring.y - 12 * Math.max(0, 1 - a) + 14 * (1 - Math.cos(rad))
  const opacity = a <= 2 ? 1 : Math.max(0.14, 1 - (a - 2) * 0.34)
  const veil = a < 0.5 ? a * 0.5 : Math.min(0.62, 0.25 + (a - 0.5) * 0.08)
  const blur = Math.max(0, a - 3) * 0.45
  node.style.transform =
    `translate(-50%,-50%) translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,${z.toFixed(1)}px) ` +
    `rotateY(${deg.toFixed(2)}deg) scale(${scale.toFixed(4)})`
  node.style.opacity = opacity.toFixed(3)
  node.style.zIndex = String(200 - Math.round(a * 20))
  node.style.filter = blur > 0.02 ? `blur(${blur.toFixed(2)}px)` : ""
  node.style.setProperty("--veil", veil.toFixed(3))
}

/** 环上的循环取模（负数也要落到 [0, n)）。 */
export const ringMod = (i: number, n: number): number => ((i % n) + n) % n

/** 把差值折到 [-n/2, n/2)。 */
export const ringSigned = (d: number, n: number): number => {
  const m = ringMod(d, n)
  return m > n / 2 ? m - n : m
}

/** 清掉一张封面上的环样式（切到平铺 / 列表布局时调）。 */
export function clearRingStyles(node: HTMLElement): void {
  for (const prop of [
    "transform", "opacity", "filter", "z-index", "visibility",
    "will-change", "transition", "pointer-events",
  ]) {
    node.style.removeProperty(prop)
  }
  node.style.removeProperty("--veil")
  delete node.dataset.ringHidden
}

/** 把这一帧算出的环尺寸写到样式变量上。 */
export function applyRingSize({
  row, viewport, size,
}: { row: HTMLElement; viewport: HTMLElement; size: RingSize }): void {
  row.style.setProperty("--gi-w", size.w + "px")
  row.style.setProperty("--gi-h", size.h + "px")
  viewport.style.setProperty("--ring-d", Math.round(size.depth) + "px")
}

/** 大厅里该排的键列表：所有可见游戏 + 末尾的「＋ 导入游戏」。 */
export function hallKeysOf(visibleIds: string[], addKey: string): string[] {
  return [...visibleIds, addKey]
}

/** 平铺布局的排布：把「焦点那张」对到视口中央，其余靠 CSS 横滑。 */
export function updateFlatRow({
  row, viewport, keys, focus, ring, instant = false,
}: {
  row: HTMLElement
  viewport: HTMLElement
  keys: string[]
  focus: string | null
  ring: { flatReady: boolean; float: number; target: number }
  instant?: boolean
}): boolean {
  const index = keys.indexOf(String(focus))
  if (index < 0) return false
  const tile = row.children[index] as HTMLElement | undefined
  if (!tile) return false
  for (const node of Array.from(row.children) as HTMLElement[]) {
    if (node.dataset.ringHidden === "1" || node.style.transform) clearRingStyles(node)
  }
  const noAnim = instant || !ring.flatReady
  if (noAnim) {
    ring.flatReady = true
    row.style.transition = "none"
  }
  const rect = viewport.getBoundingClientRect()
  const center = tile.offsetLeft + tile.offsetWidth / 2
  row.style.transform = `translate3d(${Math.round(rect.width / 2 - center)}px, 0, 0)`
  if (noAnim) requestAnimationFrame(() => { row.style.transition = "" })
  ring.float = ring.target = index
  return true
}

/** 当前主页布局 + 平铺 / 列表布局下每张封面的实际位置（全部是读 DOM）。 */
export function layoutReadout({
  row, viewport, layoutName, flatClass,
}: { row: HTMLElement; viewport: DOMRect; layoutName: string; flatClass: boolean }) {
  return {
    name: layoutName,
    flatClass,
    rowTransform: row.style.transform || "",
    viewportWidth: Math.round(viewport.width),
    tiles: (Array.from(row.children) as HTMLElement[]).map((node) => {
      const rect = node.getBoundingClientRect()
      const style = getComputedStyle(node)
      return {
        key: node.dataset.add ? "__add__" : node.dataset.id || "",
        center: Math.round(rect.left + rect.width / 2 - viewport.left),
        width: Math.round(rect.width),
        transform: style.transform,
        visible: style.visibility !== "hidden" && Number(style.opacity) > 0.05,
        focus: node.classList.contains("focus"),
      }
    }),
  }
}
