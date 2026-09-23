/** Aurora v2 · 前端内部信号（后端事件 → 需要动起来的界面）。 */
type Handler = (payload?: any) => void

const handlers = new Map<string, Set<Handler>>()

export const onUi = (name: string, fn: Handler): void => {
  if (!handlers.has(name)) handlers.set(name, new Set())
  handlers.get(name)!.add(fn)
}

export const emitUi = (name: string, payload?: any): void => {
  for (const fn of handlers.get(name) || []) {
    try {
      fn(payload)
    } catch (error) {
      console.error(`ui:${name}`, error)
    }
  }
}
