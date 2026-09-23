/**
 * Aurora v2 · DOM 小工具
 *
 * 探针（tools/e2e.py）习惯直接写 `document.getElementById('catName').value = '…'`
 * 再点保存 —— 那一步**不触发 input 事件**，靠 v-model 读不到。凡是「保存」类动作，
 * 一律在点击时刻从 DOM 读一次值：既兼容探针，也兼容输入法 / 自动填充这类场景。
 */
export function domValue(id: string, fallback = ""): string {
  const node = document.getElementById(id) as
    HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null
  if (!node) return fallback
  const value = String(node.value ?? "").trim()
  return value || fallback
}

export function domChecked(id: string, fallback = false): boolean {
  const node = document.getElementById(id) as HTMLInputElement | null
  return node ? !!node.checked : fallback
}
