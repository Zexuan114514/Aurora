/**
 * Aurora v2 · 桥接调用层（唯一出口）
 *
 * 全前端只有这一处直接摸 `window.pywebview.api`；调用点一律写成
 * `call("方法名", …)` 的字面量形式 —— tools/checks/check_contract.py 靠这个
 * 正则统计前端调用点，跟 gl/api.py 的方法名快照对比（ADR-0006）。
 */

export interface AuroraBridge {
  [name: string]: (...args: unknown[]) => Promise<unknown>
}

/** 桥接对象（pywebview 注入）；没就绪时返回 null。 */
export const bridge = (): AuroraBridge | null => {
  const api = (window as any).pywebview?.api
  return api ? (api as AuroraBridge) : null
}

/** 桥接是否可用（启动期轮询用）。 */
export const bridgeReady = (): boolean => !!bridge()

/** 调一个后端方法；方法不存在就抛错，交给调用方处理。 */
export const call = async (name: string, ...args: unknown[]): Promise<any> => {
  const api = bridge()
  if (!api || typeof api[name] !== "function") throw new Error("bridge not ready")
  return api[name](...args)
}

/** 统一把异常收进 `window.__auroraErrors`（探针靠它判断有没有静默失败）。 */
export const recordError = (where: string, error: unknown): void => {
  const message = error instanceof Error ? error.message : String(error)
  const list = ((window as any).__auroraErrors =
    (window as any).__auroraErrors || []) as string[]
  list.push(`${where}: ${message}`)
  console.error(where, error)
}
