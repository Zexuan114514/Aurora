import { describe, expect, it } from "vitest"

import {
  RING_BASE, RING_GEOMETRY, applyRingSize, clearRingStyles, hallKeysOf,
  placeRingTile, ringGeometryOf, ringMod, ringSigned,
} from "@/features/hall/geometry"

/** 一个够用的假节点：只需要 dataset 与 style（placeRingTile / clearRingStyles 只用这些）。 */
function fakeNode() {
  const style = new Map<string, string>()
  const node = {
    dataset: {} as Record<string, string>,
    style: {
      setProperty: (key: string, value: string) => { style.set(key, value) },
      removeProperty: (key: string) => { style.delete(key) },
      get transform() { return style.get("transform") || "" },
      set transform(value: string) { style.set("transform", value) },
      get opacity() { return style.get("opacity") || "" },
      set opacity(value: string) { style.set("opacity", value) },
      get zIndex() { return style.get("z-index") || "" },
      set zIndex(value: string) { style.set("z-index", value) },
      get filter() { return style.get("filter") || "" },
      set filter(value: string) { style.set("filter", value) },
      get visibility() { return style.get("visibility") || "" },
      set visibility(value: string) { style.set("visibility", value) },
      get pointerEvents() { return style.get("pointer-events") || "" },
      set pointerEvents(value: string) { style.set("pointer-events", value) },
      get willChange() { return style.get("will-change") || "" },
      set willChange(value: string) { style.set("will-change", value) },
      get transition() { return style.get("transition") || "" },
      set transition(value: string) { style.set("transition", value) },
    },
    raw: style,
  }
  return node as unknown as HTMLElement & { dataset: Record<string, string>, raw: Map<string, string> }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
const sizeAt = (w: number, h: number) =>
  ringGeometryOf({ viewportWidth: w, viewportHeight: h, geometry: RING_GEOMETRY, base: RING_BASE, clamp })

describe("环几何", () => {
  it("基准窗口下 unit = 1，封面就是基准尺寸", () => {
    const size = sizeAt(1380, 690)
    expect(size.unit).toBe(1)
    expect(size).toMatchObject({ w: 180, h: 270, rx: 580, rz: 260, depth: 1100 })
  })

  it("窗口变小/变大时按 min 比例收放，且夹在 [0.6, 1.3]", () => {
    expect(sizeAt(690, 345).unit).toBe(0.6)      // 触底
    expect(sizeAt(2760, 1380).unit).toBe(1.3)    // 触顶
    expect(sizeAt(1035, 690).unit).toBeCloseTo(0.75, 3)
  })

  it("焦点那张：角度 0、不缩放、横向位移 0", () => {
    const size = sizeAt(1380, 690)
    const node = fakeNode()
    placeRingTile(node, 0, { ring: RING_GEOMETRY, size })
    expect(node.style.transform).toContain("rotateY(0.00deg)")
    expect(node.style.transform).toContain("scale(1.0000)")
    expect(node.style.transform).toContain("translate3d(0.0px,24.0px,260.0px)")
    expect(Number(node.style.opacity)).toBe(1)
  })

  it("相邻一张：±16 度、缩小 1/(1+shrink)、透明度仍为 1", () => {
    const size = sizeAt(1380, 690)
    for (const r of [-1, 1]) {
      const node = fakeNode()
      placeRingTile(node, r, { ring: RING_GEOMETRY, size })
      const deg = Number(/rotateY\((-?[\d.]+)deg\)/.exec(node.style.transform)?.[1])
      const scale = Number(/scale\(([\d.]+)\)/.exec(node.style.transform)?.[1])
      expect(Math.abs(deg)).toBe(16)
      expect(scale).toBeCloseTo(1 / (1 + RING_GEOMETRY.shrink), 4)
      expect(Number(node.style.opacity)).toBe(1)
    }
  })

  it("越远越小、越暗：scale 单调递减、opacity 单调不增", () => {
    const size = sizeAt(1380, 690)
    const scales: number[] = []
    const opacities: number[] = []
    for (const r of [0, 1, 2, 3, 4]) {
      const node = fakeNode()
      placeRingTile(node, r, { ring: RING_GEOMETRY, size })
      scales.push(Number(/scale\(([\d.]+)\)/.exec(node.style.transform)?.[1]))
      opacities.push(Number(node.style.opacity))
    }
    for (let i = 1; i < scales.length; i++) expect(scales[i]).toBeLessThan(scales[i - 1])
    for (let i = 1; i < opacities.length; i++) expect(opacities[i]).toBeLessThanOrEqual(opacities[i - 1])
  })

  it("超过 span 的封面被彻底藏起来（visibility/opacity/pointer-events）", () => {
    const size = sizeAt(1380, 690)
    const node = fakeNode()
    placeRingTile(node, RING_GEOMETRY.span + 0.1, { ring: RING_GEOMETRY, size })
    expect(node.dataset.ringHidden).toBe("1")
    expect(node.style.visibility).toBe("hidden")
    expect(node.style.opacity).toBe("0")
    expect(node.style.pointerEvents).toBe("none")
    // 回到可见范围：样式要还回来
    placeRingTile(node, 0, { ring: RING_GEOMETRY, size })
    expect(node.dataset.ringHidden).toBe("0")
    expect(node.style.visibility).toBe("")
  })

  it("clearRingStyles 把环写过的内联样式清干净", () => {
    const size = sizeAt(1380, 690)
    const node = fakeNode()
    placeRingTile(node, 2, { ring: RING_GEOMETRY, size })
    clearRingStyles(node)
    expect(node.style.transform).toBe("")
    expect(node.style.opacity).toBe("")
    expect(node.style.zIndex).toBe("")
    expect(node.dataset.ringHidden).toBeUndefined()
  })

  it("applyRingSize 把这一帧的尺寸写进 CSS 变量", () => {
    const row = fakeNode()
    const viewport = fakeNode()
    applyRingSize({ row, viewport, size: sizeAt(690, 345) })
    expect(row.raw.get("--gi-w")).toBe("108px")
    expect(row.raw.get("--gi-h")).toBe("162px")
    expect(viewport.raw.get("--ring-d")).toBe("660px")
  })
})

describe("环上的取模与键列表", () => {
  it("ringMod 把负数也折回 [0, n)", () => {
    expect(ringMod(-1, 5)).toBe(4)
    expect(ringMod(-6, 5)).toBe(4)
    expect(ringMod(7, 5)).toBe(2)
  })

  it("ringSigned 折到 [-n/2, n/2)", () => {
    expect(ringSigned(1, 5)).toBe(1)
    expect(ringSigned(-1, 5)).toBe(-1)
    expect(ringSigned(4, 5)).toBe(-1)
    expect(ringSigned(-4, 5)).toBe(1)
  })

  it("键列表永远以「＋ 导入游戏」结尾", () => {
    expect(hallKeysOf(["a", "b"], "__add__")).toEqual(["a", "b", "__add__"])
    expect(hallKeysOf([], "__add__")).toEqual(["__add__"])
  })
})
