# ADR-0002：保留 pywebview 与无构建前端

## 状态

已接受。

## 背景

界面由 pywebview 承载（WebView2 优先、Qt 兜底），前端目前是 `index.html` + `app.css` + `app.js` 三个文件，
`app.js` 3688 行单文件 IIFE，靠 `window.__aurora.emit` 接收后端事件，靠 `window.__aurora.ring()/layout()`
与 DOM id 支撑 90 项 e2e 与视觉自检。

## 决策驱动

- 零新增运行时依赖 + 免安装单 exe（D2/D4）。
- 现有真机验证资产（e2e / visual / snap）依赖当前 DOM 与测试面，不希望重写判据。
- 单人维护，构建链是额外的长期负担。

## 考虑过的选项

1. **无构建、原生 ES 模块**：拆文件、加 `core/api.js` 与 `core/store.js`，入口仍是静态 html。
2. **引入 Vite + TypeScript 构建链**：类型安全、打包优化，但引入 npm 依赖与产物管理。
3. **保持单文件**：只做文件内分区整理。

## 决定

选择 **1**。前端按 `app/main.js` + `core/{api,store}.js` + `views/{hall,game,settings,categories}/` +
`components/` 拆分；所有桥接调用统一走 `core/api.js`；状态只经 `core/store.js` 更新；
保留 `window.__aurora`（`ring()` / `layout()`）与 `window.__auroraErrors` 作为稳定测试面。

## 后果

- ✅ 拆分收益大（3688 行 → 单文件 ≤ 400 行），不引入构建链。
- ✅ ES 模块在本地 HTTP 服务下可直接加载（P5 的资源服务与 pywebview 的 `http_port` 都满足）。
- ⚠️ 无类型系统，桥接参数错误依赖契约快照与测试发现。
- ⚠️ 缓存策略需要自己管（入口带版本参数，html/js/css 走 no-store / ETag）。

## 后续动作

- P0 冻结测试面（DOM id、`__aurora` 方法、错误收集）。
- P4 拆分后跑 `tools/e2e.py`（90 项）与 `tools/visual.py`，两者判据不改。
- 如果将来确实需要类型安全，另立 ADR 讨论「TS 仅做类型检查、不引入打包」的折中方案。
