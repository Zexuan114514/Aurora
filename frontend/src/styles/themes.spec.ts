import { readFileSync, readdirSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

/**
 * 主题契约的 JS 侧镜像（Python 守卫 tools/checks/check_theme_contract.py 是权威）。
 * 放在这里是为了让 `npm test` 单独跑也能发现「加令牌漏主题」这类问题。
 */
const STYLES = dirname(fileURLToPath(import.meta.url))
const THEMES = ["aurora", "gallery", "screening", "shelf"]

function read(path: string): string {
  return readFileSync(path, "utf8").replace(/\r\n/g, "\n")
}

function contractTokens(): string[] {
  const text = read(join(STYLES, "tokens.css"))
  const block = /\/\* @contract:start \*\/([\s\S]*?)\/\* @contract:end \*\//.exec(text)
  expect(block).toBeTruthy()
  const names = [...block![1].matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((row) => row[1])
  return [...new Set(names)]
}

function blockTokens(text: string, theme: string, light: boolean): Set<string> {
  const out = new Set<string>()
  for (const row of text.matchAll(/([^{}]+)\{([^{}]*)\}/gs)) {
    const selector = row[1].trim()
    if (!selector.includes(`[data-style="${theme}"]`)) continue
    if (selector.includes('[data-theme="light"]') !== light) continue
    for (const decl of row[2].matchAll(/(--[a-z0-9-]+)\s*:/gi)) out.add(decl[1])
  }
  return out
}

/** 主题块里的 令牌 → 值（同名取最后一次，跟 CSS 的层叠一致）。 */
function blockValues(text: string, theme: string, light: boolean): Map<string, string> {
  for (const row of text.matchAll(/([^{}]+)\{([^{}]*)\}/gs)) {
    const selector = row[1].trim()
    if (!selector.includes(`[data-style="${theme}"]`)) continue
    if (selector.includes('[data-theme="light"]') !== light) continue
    const out = new Map<string, string>()
    for (const decl of row[2].matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
      out.set(decl[1].toLowerCase(), decl[2].trim())
    }
    return out
  }
  return new Map()
}

/** `20px` → 20；不是 px 值返回 null。 */
function px(value: string | undefined): number | null {
  if (!value) return null
  const text = value.trim()
  if (!text.endsWith("px")) return null
  const n = Number(text.slice(0, -2))
  return Number.isFinite(n) ? n : null
}

/** 模糊口径（P8.8）：四套里只有极光玻璃保留毛玻璃，其余一律 0。 */
const BLUR_BY_THEME: Record<string, [number, number]> = {
  aurora: [12, 40],
  gallery: [0, 0],
  screening: [0, 0],
  shelf: [0, 0],
}

const RADIUS_LADDER = ["--r-xs", "--r-sm", "--r-md", "--r-lg", "--r-xl"]

describe("四套主题的令牌契约", () => {
  const tokens = contractTokens()

  it("契约清单本身有 20 个以上令牌", () => {
    expect(tokens.length).toBeGreaterThanOrEqual(20)
  })

  for (const theme of THEMES) {
    for (const light of [false, true]) {
      it(`${theme} · ${light ? "浅色" : "深色"}补齐全部令牌`, () => {
        const text = read(join(STYLES, "themes", `${theme}.tokens.css`))
        const declared = blockTokens(text, theme, light)
        expect(declared.size).toBeGreaterThan(0)
        expect(tokens.filter((name) => !declared.has(name))).toEqual([])
      })
    }
  }

  it("skin 文件都很短，且每条选择器都限定在自己的主题下", () => {
    for (const theme of THEMES) {
      // P8.16 起一套主题可以有多张皮肤（主题签名 + 按钮语言…）：逐张按同一口径查。
      const skins = readdirSync(join(STYLES, "themes"))
        .filter((name) => name.startsWith(theme) && name.endsWith(".skin.css"))
        .sort()
      expect(skins).toContain(`${theme}.skin.css`)
      for (const skin of skins) {
        const text = read(join(STYLES, "themes", skin))
        // P8.4 起放宽到 200 行：主题签名要能覆盖排印 / 分隔 / 封面呈现 / 背景处理。
        // 口径与 Python 守卫一致：只数**非空行**（注释与空行不算预算）。
        const budgetLines = text.split("\n").filter((row) => row.trim().length > 0).length
        expect(budgetLines, `${skin} 的行数`).toBeLessThanOrEqual(200)
        for (const row of text.matchAll(/([^{}]+)\{/g)) {
          const selector = row[1].trim()
          if (!selector || selector.startsWith("@") || selector.startsWith("/*")) continue
          expect(selector, `${skin} 的选择器`).toContain(`[data-style="${theme}"]`)
        }
      }
    }
  })

  it("四套主题文件都在（缺一套就等于少一种风格）", () => {
    const files = readdirSync(join(STYLES, "themes"))
    for (const theme of THEMES) {
      expect(files).toContain(`${theme}.tokens.css`)
      expect(files).toContain(`${theme}.skin.css`)
    }
  })

  // P8.8：契约只管「补齐了没」，这一条管「补的值合不合理」。
  // 对应 Python 守卫 tools/checks/check_theme_contract.py 的第 6 节。
  it("令牌值域合理（--s-floor 不透明度 / --fx-blur / 圆角档位单调）", () => {
    for (const theme of THEMES) {
      const text = read(join(STYLES, "themes", `${theme}.tokens.css`))
      for (const light of [false, true]) {
        const values = blockValues(text, theme, light)
        const where = `${theme} · ${light ? "浅色" : "深色"}`

        // --s-floor：面板底衬的不透明度必须落在 60–95%
        const floor = values.get("--s-floor") ?? ""
        expect(floor, `${where} 的 --s-floor`).toContain("color-mix")
        const percent = /(\d+(?:\.\d+)?)%/.exec(floor)
        expect(percent, `${where} 的 --s-floor 百分比`).toBeTruthy()
        const floorPct = Number(percent![1])
        expect(floorPct, `${where} 的 --s-floor 不透明度`).toBeGreaterThanOrEqual(60)
        expect(floorPct, `${where} 的 --s-floor 不透明度`).toBeLessThanOrEqual(95)

        // --fx-blur：只有极光玻璃保留毛玻璃
        const blur = px(values.get("--fx-blur"))
        expect(blur, `${where} 的 --fx-blur`).not.toBeNull()
        const [low, high] = BLUR_BY_THEME[theme]
        expect(blur!, `${where} 的 --fx-blur`).toBeGreaterThanOrEqual(low)
        expect(blur!, `${where} 的 --fx-blur`).toBeLessThanOrEqual(high)

        // --r-*：小 → 大单调不减
        const ladder = RADIUS_LADDER.map((name) => px(values.get(name)))
        expect(ladder.every((n) => n !== null), `${where} 的圆角档位`).toBe(true)
        for (let i = 1; i < ladder.length; i++) {
          expect(ladder[i]!, `${where} 的圆角档位 ${RADIUS_LADDER[i]}`)
            .toBeGreaterThanOrEqual(ladder[i - 1]!)
        }
      }
    }
  })
})
