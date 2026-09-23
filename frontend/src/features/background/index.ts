/** Aurora v2 · 背景层的纯工具（v1 views/background.js 里的那几个 helper）。 */

export const cssUrl = (url: string): string =>
  `url("${String(url).replace(/"/g, '\\"')}")`

/** 按名字取一个稳定的色相，用作没有壁纸时的渐变兜底。 */
export function fallbackBackground(game: { name?: string; id?: string } | null): string {
  let hue = 0
  const text = String(game?.name || game?.id || "aurora")
  for (let i = 0; i < text.length; i++) hue = (hue * 31 + text.charCodeAt(i)) % 360
  return `linear-gradient(150deg,
    hsl(${hue} 46% 26%) 0%,
    hsl(${(hue + 42) % 360} 40% 15%) 48%,
    hsl(${(hue + 96) % 360} 34% 9%) 100%)`
}

/** 当前游戏该用的背景视图（缩放只由滑杆控制，位置固定居中）。 */
export const bgViewOf = (game: { bg_scale?: number } | null) => ({
  scale: Math.max(1, Number(game?.bg_scale) || 1),
  x: 0,
  y: 0,
})
