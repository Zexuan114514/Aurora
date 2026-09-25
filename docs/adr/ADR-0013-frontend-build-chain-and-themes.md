# ADR-0013：引入前端构建链（Vue + Element Plus）与主题系统

## 状态

已接受（2026-09-22）。**部分推翻** [ADR-0002](ADR-0002-pywebview-no-build-frontend.md)
的「无构建前端」与 [ADR-0003](ADR-0003-zero-new-runtime-deps.md) 的「零新增运行时依赖」。

> **2026-09-23 更新**：下面第 3 条「新旧并行」与「回退：`AURORA_FRONTEND=v1`」
> 已被 [ADR-0014](ADR-0014-drop-v1-frontend.md) 取代 —— v1 已删除，入口固定 `/v2/index.html`。
> 第 4–7 条（一套布局 / 令牌化主题 / Element Plus 控件层 / 测试面冻结）继续有效。

> **2026-09-25 修订口径**：初始决策里的「四套主题」已在 P8.17 扩展为五套，新增
> Atelier 工作台；P8.19 又把按钮语言拆成每套独立的 `*.buttons.skin.css`。下文涉及初始
> 范围的四套数字保留作历史证据，当前主题数量和验收数字以 P8 交付记录为准。

## 背景

ADR-0002 当初选「无构建」有三条理由：零新增依赖、保住真机测试面、单人维护不想养构建链。
到 v2 这次改造时，前两条仍然成立，第三条被两件事顶开：

1. 初始界面要**四套可切换的视觉风格 × 深/浅两态**。纯手写的 ES 模块没有组件层，
   弹窗 / 下拉 / 滑块 / 表格 / 虚拟列表这些要么自己写一遍，要么一直用原生控件。
2. Element Plus 这类组件库只在 npm 生态里可用；用它就必须有构建链。

同时必须承认两件事：**运行时依赖仍然是零**（Node 只活在开发与构建期，exe 里没有 Node），
以及**测试面不能丢** —— `tools/e2e.py`（97 项）与 `tools/visual.py` 的环形判据是这几年
真机踩出来的回归网，重写等于把网拆了重织。

## 决策

1. **构建链只进开发期**：`frontend/` 是 Vite + Vue 3 + TypeScript 工程，
   `npm run build` 产出到 `gl/web/v2/`（随源码入库）。运行 exe 不需要 Node、不需要 npm。
2. **产物入库 + 指纹守卫**：`gl/web/v2/build-info.json` 记源码树哈希，
   `tools/checks/check_frontend_build.py`（纯 Python）重算比对 —— 改了源码没重建就红，
   于是 CI 的主 job 仍然不需要 Node。
3. **新旧并行**：v1（无构建 ES 模块）保留在 `gl/web/`，v2 在 `gl/web/v2/`，
   由环境变量 `AURORA_FRONTEND=v1|v2` 选择（默认 v2，v2 目录缺失自动回落 v1）。
   ~~（2026-09-23 由 ADR-0014 取代：v1 已删，入口固定 `/v2/index.html`。）~~
4. **布局只有一套，风格全在 CSS**：`src/styles/layout.css` 由 v1 的 `app.css` 机械迁移，
   环形封面流的几何与所有判据不动；颜色 / 圆角 / 模糊 / 阴影全部抽成语义令牌，
   五套主题（极光玻璃 / 展签式画廊 / 夜间放映厅 / 收藏架 / Atelier 工作台）× 深/浅两态只是令牌的不同取值。
5. **主题可运行时切换**：`<html data-style="…" data-theme="dark|light">` 两个属性决定外观，
   切换不重载、不重新构建。`data-theme` 保留 v1 语义（dark / light），否则 e2e 的
   浅色主题判据会红；风格走 `data-style`。
6. **Element Plus 作为控件层**：按钮 / 输入 / 下拉 / 滑块 / 弹窗 / 提示 / 虚拟列表用它，
   通过 `--el-*` 变量桥接语义令牌，五套主题自动跟随；主题专属按钮外观另由
   `<theme>.buttons.skin.css` 提供。
   环形封面流与游戏页大图属于自绘层，不套组件库。
7. **测试面冻结**：92 个 DOM id、`window.__aurora.ring()/layout()/emit()`、
   `__auroraErrors`、14 个事件主题、`tools/e2e.py` 的 97 项判据与 `visual.py` 的环形基线
   在 v2 上必须原样通过；只允许新增 `data-testid`，不允许改判据。
   `tools/checks/check_frontend_surface.py` 用快照（`contracts/frontend-surface.json`）守住这条。

## 后果

- ✅ 组件能力与主题能力一步到位；五套风格共用一个 DOM，加风格 = 加令牌、签名和按钮皮肤文件。
- ✅ 运行时依赖仍是零：Node 缺失、npm 没装都不影响 exe 运行（只影响重新构建）。
- ✅ CI 主 job 保持纯 Python；Node 只在第二个 job 里跑 `vue-tsc` 与 `vitest`。
- ⚠️ 仓库里多了一棵 `frontend/` 源码树与 `gl/web/v2/` 产物树，review 时要看的是源码，
  产物由指纹守卫保证与源码一致。
- ✅ 包体：v2 产物未压缩 430 KB（首版全量引 Element Plus 时是 1.5 MB，
  P8.1 按需引入后回到上限内；组件库 CSS 只剩 18 KB）；
  WebView2 解析 Vue + Element Plus 比 v1 多一次首帧开销（预算：首帧可交互 ≤ 基线 + 200ms）。
- ⚠️ 主题矩阵带来测试成本：当前截图基线按五套主题的深浅配置生成 **35 张**，
  不做更多组合的全量逐像素比对。已落在 `tools/visual.py` + `tools/baselines/theme-baseline.json`
  （16×10 网格平均色，容差 ±12；重录：`$env:VISUAL_UPDATE_THEME_BASELINE="1"`）。
- 🔁 回退：~~`AURORA_FRONTEND=v1` 立刻回到旧前端（v1 不删）；彻底回退用 git 回滚该版本。~~
  （2026-09-23 起见 ADR-0014：回退只能靠 git 回滚，运行期不再有版本开关。）

## 后续动作

- ~~v2 全绿一个版本后，另立 ADR 决定是否删除 v1（`gl/web/*.js` 与 `app/`）与
  `check_packaging` 里的 v1 分支。~~ → 已在 [ADR-0014](ADR-0014-drop-v1-frontend.md) 落地（2026-09-23）。
- 若未来要删 Element Plus，替换面只有 `src/styles/element.css` 与用到 `el-` 组件的模板。
- Element Plus 目前按需引入（tooltip / switch / slider）：加组件要同时改
  `src/core/element.ts` 与 `src/styles/element-plus.css`，`src/core/element.spec.ts` 会核对两份清单。
