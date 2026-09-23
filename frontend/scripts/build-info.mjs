/**
 * 构建指纹：把「源码树」哈希写进 gl/web/v2/build-info.json。
 *
 * tools/checks/check_frontend_build.py 用同一套算法在 Python 侧重算，
 * 对不上就说明「改了源码没重新构建」——CI 不需要装 Node 也能拦住。
 */
import { createHash } from "node:crypto"
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { dirname, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const outDir = resolve(root, "..", "gl", "web", "v2")
const SOURCE_EXT = new Set([".ts", ".vue", ".css", ".html", ".json", ".mjs"])
const SKIP_DIRS = new Set(["node_modules", "dist", ".vite", "__pycache__"])
const SKIP_FILES = new Set(["package-lock.json", "build-info.json"])
// Vite 转译 TS 配置时会在 frontend/ 根留下 `vite.config.ts.timestamp-*.mjs`。
// 正常它会自己删掉；删不掉时（权限 / 沙箱）会污染指纹 —— 与 check_frontend_build.py 同步跳过。
const SKIP_NAME = /^vite\.config\..*timestamp-.*\.mjs$/

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) walk(join(dir, entry.name), acc)
    } else if (entry.isFile()) {
      if (SKIP_FILES.has(entry.name) || SKIP_NAME.test(entry.name)) continue
      const ext = entry.name.slice(entry.name.lastIndexOf("."))
      if (!SOURCE_EXT.has(ext)) continue
      acc.push(join(dir, entry.name))
    }
  }
  return acc
}

const files = walk(root).sort((a, b) => (relative(root, a) < relative(root, b) ? -1 : 1))
const hash = createHash("sha256")
for (const file of files) {
  const rel = relative(root, file).split("\\").join("/")
  const body = readFileSync(file, "utf8").split("\r\n").join("\n")
  hash.update(rel)
  hash.update("\n")
  hash.update(body)
  hash.update("\n")
}

const info = {
  schema: "aurora.frontend-build/1",
  source: "frontend/",
  algorithm: "sha256(relpath\\n + lf-normalised body\\n, sorted by relpath)",
  hash: hash.digest("hex"),
  files: files.length,
}

writeFileSync(join(outDir, "build-info.json"), JSON.stringify(info, null, 2) + "\n", "utf8")
console.log(`build-info: ${info.files} 个源文件 → ${info.hash.slice(0, 12)}`)
