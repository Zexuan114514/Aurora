/**
 * Aurora v2 · 主题与深浅模式
 *
 * 视觉风格只由两个根属性决定：
 *   <html data-style="aurora|gallery|screening|shelf" data-theme="dark|light">
 * 切换只改属性，不重载、不重新构建 —— 四套主题的 CSS 始终都在包里。
 * 旧的「调色板 / 强调色 / 模糊 / 压暗」四个设置只读兼容，不再写回。
 *
 * 注意属性名不是随便起的：`data-theme` 保持 v1 的语义（dark / light），
 * 否则 tools/e2e.py 里那两条判据（浅色主题生效 / 能切回深色）会红。
 * 风格走 `data-style`，调色板走 `data-palette`。
 */
import { call } from "@/core/api"

export const THEMES = [
  { id: "aurora", name: "极光玻璃", hint: "毛玻璃 + 极光青紫，最接近旧版观感" },
  { id: "gallery", name: "展签式画廊", hint: "界面退成展签，细线、无圆角、无投影" },
  { id: "screening", name: "夜间放映厅", hint: "暖黑底 + 琥珀，主封面像正在放映" },
  { id: "shelf", name: "收藏架", hint: "封面立在架上，黄铜分隔，纸质说明卡" },
] as const

export const THEME_IDS = THEMES.map((row) => row.id) as string[]
export const MODES = ["dark", "light", "auto"] as const

/** 旧的四套调色板（e2e 会点 #setPalettes[data-palette=lime]，所以保留）。 */
export const PALETTES = [
  { key: "aurora", name: "跟随主题", accent: "", accent2: "" },
  { key: "lime", name: "薄荷青", accent: "#26C6A8", accent2: "#6FE0C8" },
  { key: "sakura", name: "樱花粉", accent: "#FF5C8A", accent2: "#FF9AB6" },
  { key: "amber", name: "琥珀橙", accent: "#FF9F0A", accent2: "#FFC46B" },
] as const

const lightQuery = window.matchMedia
  ? window.matchMedia("(prefers-color-scheme: light)")
  : null

/** 设置里的 theme_mode（dark / light / auto）→ 实际生效的 data-mode。 */
export function effectiveMode(setting?: string): "dark" | "light" {
  const mode = setting || "dark"
  if (mode === "auto") return lightQuery?.matches ? "light" : "dark"
  return mode === "light" ? "light" : "dark"
}

/** 设置里的 theme 值，非法值退回默认主题。 */
export function effectiveTheme(setting?: string): string {
  return THEME_IDS.includes(String(setting)) ? String(setting) : "aurora"
}

/** 把主题写到 <html> 上，并同步窗口边框（后端按明暗决定 DWM 描边）。 */
export function applyTheme(settings: Record<string, any>): void {
  const mode = effectiveMode(settings.theme_mode)
  const theme = effectiveTheme(settings.theme)
  const root = document.documentElement
  root.dataset.theme = mode          // v1 语义：dark / light（探针判据）
  root.dataset.style = theme         // 四套视觉风格
  root.dataset.palette = String(settings.palette || "aurora")
  try {
    call("apply_window_theme", mode === "light").catch(() => {})
  } catch {
    /* 离线（无桥接）时忽略 */
  }
}

/** 跟随系统：只有 theme_mode = auto 时才需要重新应用。 */
export function watchSystemMode(settings: Record<string, any>): void {
  if (!lightQuery) return
  const onChange = () => {
    if ((settings.theme_mode || "dark") === "auto") applyTheme(settings)
  }
  if (lightQuery.addEventListener) lightQuery.addEventListener("change", onChange)
  else if ((lightQuery as any).addListener) (lightQuery as any).addListener(onChange)
}
