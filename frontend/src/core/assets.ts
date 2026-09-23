/**
 * Aurora v2 · 素材地址归一
 *
 * 后端（aurora/app/projection.py）把老数据里的 `userbg/…` / `usercovers/…` / `usericon/…`
 * 改写成 `assets/…` —— 这是**相对页面**的写法。v1 的页面在服务根目录（`/index.html`），
 * 所以 `assets/…` 正好解析成 `/assets/…`；v2 的页面在 `/v2/index.html`，
 * 相对路径会解析成 `/v2/assets/…` → 404（真机冒烟抓到的就是这个）。
 *
 * 因此在 store 的入口统一把这类地址补成绝对路径 `/assets/…`：
 * 只改路径写法，不动磁盘上的数据和后端的投影规则。
 */

const RELATIVE_PREFIXES = [
  "assets/", "userbg/", "usercovers/", "usericon/",
]

/** 把后端给的相对素材地址补成服务根下的绝对路径；其它地址原样返回。 */
export function fixAssetUrl(url?: string | null): string {
  const value = String(url || "").trim()
  if (!value) return ""
  if (/^(https?:|data:|blob:|file:)/i.test(value)) return value
  if (value.startsWith("/")) return value
  for (const prefix of RELATIVE_PREFIXES) {
    if (value.startsWith(prefix)) {
      const rest = value.slice(prefix.length)
      const mount = prefix === "assets/" ? "" : `${prefix.replace(/\/$/, "")}/`
      // 老写法（userbg/xxx.png）等价于 assets/backgrounds/xxx.png 的上一代路径，
      // 后端已经不再产出；这里按 /assets/<原名> 兜底，至少不会指向 /v2 下。
      return mount ? `/assets/${mount}${rest}` : `/assets/${rest}`
    }
  }
  return value
}

/** 游戏实体里的所有素材字段都过一遍归一。 */
export function normalizeGame<T extends Record<string, any>>(game: T): T {
  if (!game || typeof game !== "object") return game
  const fixed: Record<string, any> = { ...game }
  for (const key of ["cover", "custom_cover", "custom_icon", "header_image", "logo", "background"]) {
    if (fixed[key]) fixed[key] = fixAssetUrl(fixed[key])
  }
  if (Array.isArray(fixed.cover_sources)) {
    fixed.cover_sources = fixed.cover_sources.map((url: string) => fixAssetUrl(url))
  }
  if (Array.isArray(fixed.images)) {
    fixed.images = fixed.images.map((image: Record<string, any>) => ({
      ...image,
      url: fixAssetUrl(image?.url),
      thumb: image?.thumb ? fixAssetUrl(image.thumb) : image?.thumb,
    }))
  }
  return fixed as T
}
