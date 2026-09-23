# ADR-0014：删除 v1 前端（无构建 ES 模块）

## 状态

已接受（2026-09-23）。**取代** [ADR-0013](ADR-0013-frontend-build-chain-and-themes.md)
第 3 条「新旧并行」与它「回退：`AURORA_FRONTEND=v1`」的结论；
同时收口 [ADR-0002](ADR-0002-pywebview-no-build-frontend.md) 里「保留无构建前端」那一段
（v1 就是那个无构建前端，现在删了）。

## 背景

ADR-0013 引入 v2 时把「新旧并行」当作过渡手段，理由是**回退要便宜**：
`AURORA_FRONTEND=v1` 一行环境变量就能回到旧前端，v2 产物缺失时也能自动回落。

到 P8.9 时，这条过渡的收益已经用完，成本还在涨：

1. **v2 已经连续多轮全绿**：`e2e` 96/96、`contrast` 32/32、主题矩阵 25/25（偏差 0）、
   `run_all` 14/14、`pytest` / `vue-tsc` / `vitest` 全过。回退的必要性没了。
2. **两棵树都要跟着改**：P8.6 把 `#btnGetGames` / `#scopePill` 搬进顶部栏时，
   v1 也得同步改一遍 —— 否则「回退」回到的是一个功能已经落后的界面。
3. **守卫的扫描面停在 v1 上**：`check_contract` / `check_layers` / `check_bridge`
   都还在扫 `gl/web/app.js` + `gl/web/app/**`。真正在跑的是 `frontend/src`，
   于是「前端调用点 100 个全部有后端实现」这句话，验的是一棵没人再跑的树。
4. **打包清单要登记两套**，文档里「v1 还在」的口径要一直维护。

## 决策

1. **删除 v1 源码**：`gl/web/index.html`、`gl/web/overlay.html`、`gl/web/app.css`、
   `gl/web/app.js`、`gl/web/app/**`（22 个文件，`git rm`）。
2. **入口固定 `/v2/index.html`**：`main.py` 去掉 `FRONTEND_MODES` 与 `frontend_mode()`；
   产物缺失只记一条明确的日志（提示先 `npm run build`），不再静默回落 v1。
   `AURORA_DEV_URL`（开发时指向 Vite dev server）保留。
3. **打包清单收成一套**：`tools/build_exe.py` 的 `WEB_FILES` 清空、
   `WEB_MODULE_DIRS = ("v2",)`；`check_packaging` 的「顶层无未登记条目」因此只剩 `v2`。
4. **守卫扫描面换成 v2 源码**：`tools/checks/common.py` 新增 `frontend_sources()`，
   按「主窗 / 悬浮窗」分开取 `frontend/src` 下的 `.ts` / `.vue`（测试文件不算调用点）。
   - `check_contract` / `update_contract`：主窗调用点走 `frontend_sources(overlay=False)`；
     悬浮窗的 `called_by_frontend` 也改为按源码算，不再写死四个动作名。
   - `check_layers` 规则 2：主窗源码里只允许 `core/api.ts` 直接摸 `window.pywebview`
     （`main.ts` 的探活改为复用 `core/api.ts` 的 `bridge()`）。悬浮窗是独立窗口、
     有自己的桥接对象，不在这一条里。
   - `check_bridge`（人读版）：主窗 + 悬浮窗分开统计。
5. **架构基线登记搬家**：`tools/checks/baseline.json` 的 `superseded_by` 把 22 个 v1
   路径映射到 v2 对应文件（`gl/web/app.js` → `gl/web/v2/bundle/main-*.js`、
   `gl/web/app/views/hall.js` → `frontend/src/views/HallView.vue` …）；
   `bridge.frontend_call_points` 100 → 103（v2 主窗的实际调用点）。

## 后果

- ✅ 只剩一棵前端树：守卫扫的就是在跑的源码，`frontend_call_points` 从「验 v1」
  变成「验 v2」（100 → 103，多的 5 个是常驻背景与术语表相关的方法）。
- ✅ 打包清单、文档口径、README 的目录树都少一套要维护的东西。
- ✅ 包体少 22 个文件（未压缩约 100 KB）。
- ⚠️ **回退路径从「环境变量」变成「git 回滚」**：运行期不再有开关。
- ⚠️ 少了「v2 产物缺失自动回落」这层保险：产物漏了会白屏。改用三道离线门兜住 ——
  `check_frontend_build`（源码指纹 vs `build-info.json`）、
  `check_packaging`（`gl/web/v2` 的形状：两个 html + bundle 里有 js/css + 指纹）、
  `build_exe.py --dry-run`（打包输入自检）。
- ⚠️ 前端源码改动后必须重建产物并一起提交，否则 `check_frontend_build` 会红。

## 后续动作

- 改前端后的固定动作：`cd frontend && npm run build`（产物落 `gl/web/v2/`，随源码入库），
  再 `python tools\build_exe.py` 重建 `Aurora.exe`。
- 若将来要彻底推翻 pywebview（ADR-0002），前端这一层已经只有 `frontend/` 一处源码，
  迁移面比并行期小一半。
