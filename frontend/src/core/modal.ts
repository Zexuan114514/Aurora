/** Aurora v2 · 输入 / 确认对话框（v1 主模块的 modal() 等价物，返回 Promise）。 */
import { reactive } from "vue"

export interface ModalOptions {
  title?: string
  body?: string
  input?: boolean
  value?: string
  okText?: string
  presets?: string[]
}

export const modalState = reactive({
  open: false,
  title: "提示",
  body: "",
  input: false,
  value: "",
  okText: "确定",
  presets: [] as string[],
})

let resolver: ((value: any) => void) | null = null

export function modal(options: ModalOptions): Promise<any> {
  modalState.title = options.title || "提示"
  modalState.body = options.body || ""
  modalState.input = !!options.input
  modalState.value = options.value || ""
  modalState.okText = options.okText || "确定"
  modalState.presets = options.presets || []
  modalState.open = true
  if (options.input) {
    setTimeout(() => {
      const node = document.getElementById("modalInput") as HTMLInputElement | null
      node?.focus()
      node?.select()
    }, 60)
  }
  return new Promise((resolve) => { resolver = resolve })
}

export function resolveModal(ok: boolean): void {
  const done = resolver
  // 输入框的值以 DOM 为准：探针 / 自动化会直接写 .value 再点确定（不触发 input）
  if (ok && modalState.input) {
    const node = document.getElementById("modalInput") as HTMLInputElement | null
    if (node) modalState.value = node.value
  }
  resolver = null
  modalState.open = false
  if (!done) return
  done(ok ? (modalState.input ? modalState.value.trim() : true) : null)
}
