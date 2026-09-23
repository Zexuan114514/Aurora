import { readFileSync, readdirSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import { describe, expect, it } from "vitest"

/**
 * Element Plus 是按需引入的（见 styles/element-plus.css 注释）。
 * 模板里写 `<el-xxx>` 但忘了注册组件 / 引样式时，构建不会报错、界面直接少一块，
 * 所以这个用例把三份清单钉在一起：
 *
 *   模板用到的  ==  core/element.ts 注册的  ==  styles/element-plus.css 引的
 *
 * 加组件要三处一起加；`el-popper` / `base` 属于基础设施（提示层与变量），
 * 不在组件名对照里。
 */
const CORE = dirname(fileURLToPath(import.meta.url))
const SRC = join(CORE, "..")
const STYLES = join(SRC, "styles")
const INFRA = new Set(["base", "el-popper"])
//: 提示层没有自己的样式文件（el-tooltip.css 是空壳），样式挂在 el-popper 上
const CSS_FOR: Record<string, string> = { "el-tooltip": "el-popper" }

const kebab = (name: string) => name.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase()

function vueFiles(dir: string): string[] {
  const out: string[] = []
  for (const row of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, row.name)
    if (row.isDirectory()) out.push(...vueFiles(path))
    else if (row.name.endsWith(".vue")) out.push(path)
  }
  return out
}

function usedTags(): string[] {
  const found = new Set<string>()
  for (const file of vueFiles(SRC)) {
    const text = readFileSync(file, "utf8")
    for (const row of text.matchAll(/<(el-[a-z0-9-]+)/g)) found.add(row[1])
  }
  return [...found].sort()
}

function registered(): string[] {
  const text = readFileSync(join(CORE, "element.ts"), "utf8")
  const block = /const COMPONENTS = \{([^}]*)\}/.exec(text)
  expect(block).toBeTruthy()
  return [...block![1].matchAll(/\b(El[A-Za-z0-9]+)\b/g)].map((row) => kebab(row[1])).sort()
}

function imports(): string[] {
  const text = readFileSync(join(STYLES, "element-plus.css"), "utf8")
  return [...text.matchAll(/@import\s+"element-plus\/theme-chalk\/([a-z0-9-]+)\.css"/g)]
    .map((row) => row[1])
}

/** 组件清单 = 除了基础设施（变量与提示层底座）以外的样式文件。 */
function styled(): string[] {
  return imports().filter((name) => !INFRA.has(name)).sort()
}

function hasCss(tag: string): boolean {
  return imports().includes(CSS_FOR[tag] || tag)
}

describe("Element Plus 按需引入清单", () => {
  it("模板里用到的组件都注册了", () => {
    const missing = usedTags().filter((tag) => !registered().includes(tag))
    expect(missing).toEqual([])
  })

  it("模板里用到的组件都引了 theme-chalk 样式", () => {
    const missing = usedTags().filter((tag) => !hasCss(tag))
    expect(missing).toEqual([])
  })

  it("注册清单与样式清单一一对应（不引全量样式，也不多注册）", () => {
    const owners = [...styled(), ...usedTags().filter((tag) => CSS_FOR[tag])]
    expect(registered()).toEqual([...new Set(owners)].sort())
  })

  it("没有退回全量引入", () => {
    const app = readFileSync(join(SRC, "main.ts"), "utf8")
    expect(app).not.toContain("element-plus/dist/index.css")
    expect(app).not.toMatch(/^\s*import[^\n]*element-plus/m)
    expect(app).not.toMatch(/app\.use\(/)
  })
})
