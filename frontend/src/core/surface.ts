/**
 * Aurora v2 · 自检读出面（冻结的测试面）
 *
 * 这一层是 tools/e2e.py 与 tools/visual.py 唯一的取数口子，形状必须与 v1 一致：
 *   window.__aurora.ring()    → { float, target, drag, focus, keys }
 *   window.__aurora.layout()  → { name, flatClass, rowTransform, viewportWidth, tiles[] }
 *   window.__aurora.emit(topic, payload)
 *   window.__aurora.dispatch(envelopeJson)   （契约里的目标形态）
 *   window.__auroraErrors     → string[]
 */
import { emitEvent, dispatchEnvelope } from "@/core/events"

interface SurfaceSource {
  ring: () => any
  layout: () => any
}

let source: SurfaceSource | null = null

export function installSurface(next: SurfaceSource): void {
  source = next
  const w = window as any
  w.__auroraErrors = w.__auroraErrors || []
  w.__aurora = {
    ring: () => (source ? source.ring() : { float: 0, target: 0, drag: false, focus: null, keys: [] }),
    layout: () => (source ? source.layout() : {
      name: "unknown", flatClass: false, rowTransform: "", viewportWidth: 0, tiles: [],
    }),
    emit: (topic: string, payload: Record<string, any>) => emitEvent(topic, payload),
    dispatch: (raw: string) => dispatchEnvelope(raw),
  }
}

/** 组件挂载后把真的取数实现接进来（大厅的 ring / layout）。 */
export function updateSurface(next: SurfaceSource): void {
  source = next
}

export function reportSurfaceError(message: string): void {
  const w = window as any
  w.__auroraErrors = w.__auroraErrors || []
  w.__auroraErrors.push(message)
}
