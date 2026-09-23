import { fileURLToPath, URL } from "node:url"

import vue from "@vitejs/plugin-vue"
import { defineConfig } from "vitest/config"

/**
 * 产物直接落到 gl/web/v2/（随源码入库，由 tools/checks/check_frontend_build.py 守卫）。
 *
 * 两个必须记住的约束：
 *   1. assetsDir 不能是 `assets` —— 本地静态服务的 `/assets/` 是用户素材挂载点
 *      （背景 / 封面 / 图标），Vite 默认的 `assets/` 会把它盖掉。
 *   2. build.target 固定 chrome87 —— Qt 回退内核的 Chromium 比 WebView2 旧。
 */
export default defineConfig({
  base: "./",
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: fileURLToPath(new URL("../gl/web/v2", import.meta.url)),
    emptyOutDir: true,
    assetsDir: "bundle",
    target: "chrome87",
    cssTarget: "chrome87",
    sourcemap: false,
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        overlay: fileURLToPath(new URL("./overlay.html", import.meta.url)),
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.spec.ts"],
  },
})
