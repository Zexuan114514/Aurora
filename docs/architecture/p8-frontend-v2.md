# P8 交付记录：前端 v2（Vue 3 + Element Plus + 四套主题）

## Summary

按 [ADR-0013](../adr/ADR-0013-frontend-build-chain-and-themes.md) 落地的第二套前端：
`frontend/` 是 Vite + Vue 3 + TypeScript + Element Plus 工程，构建产物在 `gl/web/v2/`。
（P8.9 起 v1 已删，见 [ADR-0014](../adr/ADR-0014-drop-v1-frontend.md)：不再有
`AURORA_FRONTEND` 开关，入口固定 `/v2/index.html`。）

视觉上是**四套可切换风格 × 深/浅两态**：极光玻璃（默认）/ 展签式画廊 / 夜间放映厅 / 收藏架。
布局只有一套（`src/styles/layout.css`，由 v1 的 `app.css` 机械迁移），
风格全部是语义令牌的不同取值 —— 加一套风格 = 加两个 CSS 文件，不动组件、不重新构建。

### 续做（P8.1，同日）

首版交付后把「还没做的」里能落地的都做完了，顺带修掉迁移时漏掉的四个设置键：

- **Element Plus 按需引入**：`gl/web/v2` 未压缩从 1561 KB → **430 KB**（组件库 CSS 431 KB → 18 KB，
  入口 JS 1.07 MB → 253 KB），回到 ADR-0013 里 1500 KB 的上限内。
- **设置页控件替换（第一批）**：7 个开关换 `el-switch`、3 个滑杆换 `el-slider`；
  探针直接读 `.value` / `.checked` / `.options` 的节点（下拉框、路径框、两个开关）保持原生。
- **主题截图基线**：`tools/visual.py` 增加主题矩阵（深色 4 套 + 浅色默认主题 × 5 界面 = 25 张），
  指纹存 `tools/baselines/theme-baseline.json`，`tools/visual_summary.py` 出汇总。
- **修掉四个「能拖但不落盘」的设置**：`vntext_context` / `vntext_auto` / `{fontSize}` / `{alpha}`
  以及取词方式的 `textractor` 五个名字后端都不认（一律回 `ok:false`，界面照常动，设置没存）；
  已按 `aurora/infra/config.py` 的 `DEFAULT_SETTINGS` 对齐，并加了离线守卫
  `tools/checks/check_settings_keys.py`（第 14 项检查）钉住这条契约。

### 续做（P8.2）

- **设置页控件替换（第二批）**：19 个普通按钮换 `el-button`、8 个文本框换 `el-input`
  （`#setTransBase` / `#setTransKey` / `#setTransModel` / `#setProxyUrl` / `#setLePath` /
  `#setVnPath` / `#glossarySrc` / `#glossaryDst`）。视觉仍由 `layout.css` 的
  `.btn` / `.glass-btn` / `.mini-btn` 决定（class 原样带过去），Element Plus 提供的是行为层。
  剩下的下拉框与复合控件（`set-tab` / `theme-card` / `palette-chip` / `menu-row` / `vn-build`）不动：
  它们是自绘的列表行与卡片，换组件只有损失没有收益，而且 4 个下拉是探针直接读 `.value` / `.options` 的。
  产物随之涨到 485 KB（多出 el-button / el-input 两份 CSS，共 ~31 KB），仍远低于上限。
- **滑杆值域进守卫**：`check_settings_keys.py` 现在还会核对三个滑杆的 `:min` / `:max`
  与后端 clamp 区间一致（`vntext_context_lines` 0–12、`font` 12–40、`opacity` 35–100）。
  后端对越界值是**静默夹**，滑杆跑出去不会报错，之前只能靠人看。

### 续做（P8.3）：主题外观取向 + 常驻背景

对着 `docs/theme-demos/` 的四套示例页与 `reference/` 的三张 Gal Launcher 截图过了一遍，
这一轮落地两件明确的事（其余取向见文末「主题外观重构（待确认）」）：

- **极光玻璃去掉那层轻模糊**：`aurora.tokens.css` 深浅两块的 `--fx-blur` 都改成 `0px`，
  `aurora.skin.css` 里重复的那段 `backdrop-filter` 删掉，`tokens.css` 的契约默认值
  也改成 0（默认主题不再自带模糊）。面板仍然是「半透明底 + 1px 细边」，靠
  `--s-floor`（面板色 68%）保证文字可读 —— 去掉模糊后 `tools/contrast.py` 复测见验收表。
- **背景默认跟随当前游戏，可钉一张常驻图（只支持一张）**：
  - 后端：`DEFAULT_SETTINGS` 增加 `background_mode`（`game` / `custom`）、
    `background_custom`（`assets/backgrounds/persistent-*`）、`background_custom_scale`；
    `LibraryBridgeMixin` 增加 `get_background_state` / `set_background_mode` /
    `pick_persistent_background` / `clear_persistent_background` /
    `set_background_custom_scale`（选图时会把上一张删掉，永远只有一张）。
    桥接快照同步：151 → 159 方法（`tools/checks/update_contract.py --write`）。
  - 前端：`BackgroundLayer` 按 `background_mode` 决定用常驻图还是当前游戏的壁纸，
    并监听 `settings:applied`；路径过 `fixAssetUrl()`（v2 在 `/v2/` 下，相对 `assets/…`
    会解析错——这个坑真机探针抓到过一次）。背景面板顶部是
    「背景 · 跟随当前游戏 / 背景 · 常驻图」两个胶囊，常驻态多一行「更换图片… / 清除」，
    缩放滑杆在常驻态写 `background_custom_scale`，点缩略图会先切回 game 再应用。

## 验收证据（2026-09-22，真机）

| 门 | 结果 |
| --- | --- |
| `tools/e2e.py`（v2） | **95/95 passed, 0 skipped** |
| `tools/visual.py`（v2） | ring 判据与文档逐项一致：`0/347.0`、`±16/283.2`、`32/232.5`；主题矩阵 **25/25** 在容差内（最大偏差 0，容差 ±12）；`errors=[]` |
| `tools/contrast.py`（真机） | 4 套风格 × 深/浅 × 2 页面 = **32/32 达标**（正文阈值 4.5、大字 3.0；最低 7.8，出现在 aurora-dark 游戏页标题），**去掉极光玻璃的模糊后复测** |
| `tools/checks/run_all.py` | **14/14**（v2 新增 4 项：前端构建新鲜度 / 主题契约与基线 / 前端测试面 / 设置键名） |
| `python -m pytest` | 全绿（含本次未改动的 vntext / 迁移 / 冷启动用例） |
| `npm run typecheck`（vue-tsc） | 通过 |
| `npm run test`（vitest） | 37 项通过（环几何 11 / 主题契约 11 / 时间 4 / 查询 7 / 按需清单 4） |
| 产物体积 | `gl/web/v2` 未压缩 **488 KB**（上限 1500 KB）：3 js + 3 css + `build-info.json` |
| 示例页扁平度（`_sandbox/element_flatness.py`） | 四套 × 按钮/面板：`linear-gradient` / `radial-gradient` / `box-shadow` / `inset` / `backdrop-filter` **全为 0**（v3 把极光最后那层模糊也去掉了） |
| 常驻背景探针（`_sandbox/probe_persistent_bg.py`） | 默认跟随游戏 ✓ / 切常驻图 ✓ / 缩放写 `background_custom_scale` ✓ / 切回 ✓ / 清除并删文件 ✓ / 无前端报错 |
| 区分度（`visual.py` 新增口径） | 深色四套两两平均色差 **8.6 / 目标 ≥ 20**（参照：深/浅两态 193）—— 只报数不判红，见「主题外观重构（待确认）」 |
| `tools/build_exe.py --dry-run` | 通过（前端清单含 `v2/` 产物树） |
| `Aurora.exe`（重建） | 24.6 MB；打包树含 `v2/`（`_build/web-stage` 31 个文件）；启动日志 `frontend entry (v2): …/v2/index.html` |
| 真机冒烟（`tools/snap.py`） | `__auroraErrors = []`；24 个真实游戏正常渲染；主题热切换生效 |

### 续做（P8.3：体验反馈里的两条可读性 / 布局问题）

使用者 2026-09-22 反馈了三条外观问题（[`../frontend-ux-feedback.md`](../frontend-ux-feedback.md)），
先修了其中两条：

1. **强调色胶囊文字换行 / 溢出**：根因是 `layout.css` 里 `.set-row span`（行尾数值位用的）
   写成了后代选择器，把胶囊里的 `span` 与 `.palette-custom` 一起套成 34px 宽。
   收紧成 `.set-row > span` 一处改完（顺手把 P8.1/P8.2 那几处组件内部泄漏也一起根治）。
2. **深色态文字在亮壁纸上不可读**：两个原因叠加 ——
   （a）面板没有底色，`.glass` / `.set-nav` / `.set-panes` 只有 3.5%–13.5% 的白 + 模糊，
   等于 96% 的壁纸；新增派生令牌 `--s-floor`（`--s-panel` 68%）给内容面板垫底；
   （b）`#bg-scrim` / `#bg-vignette` 的 `rgba(var(--scrim-rgb), α)` 是**非法语法**
   （`--scrim-rgb` 是 `0 0 0` 这种空格三通道），整条 background 被丢掉 ——
   也就是说「按壁纸明暗压暗」这个功能**从来没生效过**。改成 `rgb(var(--scrim-rgb) / α)` 后才真正工作，
   并给游戏页信息列加了一层不随用户 scrim 归零的保底（`body.page-game`）。

复测：设置页说明文字（深色）1.04–3.31 → **8.10–13.01**；游戏页简介（深色）1.04–1.76 → **11.59–16.83**；
浅色态没有回退。新增真机自检 [`tools/contrast.py`](../../tools/contrast.py)：32 个采样点、
正文 ≥4.5 / 大字号 ≥3.0，作为一个与 e2e / visual 同级的门（`tools/checks/tools-manifest.json` 已登记）。

主题截图基线随之重录并复验：**25/25 在容差内（最大偏差 0）**，ring 判据
`0/347.0`、`±16/283.2`、`32/232.5` 一字未变。顺带给 `visual.py` 的主题段加了三条自检
（主题切没切过去 / 页面到不到位 / 截出来的明暗对不对），任一不满足就跳过该张并报出来 ——
之前录基线时把「换主题没画完」的帧当成外观录进去过。第 2 条（四套主题区分度）留给下一轮。

## 结构

```
frontend/                     Vite 工程（Node 只在开发 / 构建期）
  index.html / overlay.html   两个入口（主窗 + 悬浮窗）
  src/core/                   api（唯一桥接出口）/ store / events / surface /
                              query / time / theme / assets / shell / window / actions /
                              element（Element Plus 按需注册清单）
  src/features/hall/          环形几何（纯函数，逐字从 v1 迁移）+ 环运行期
  src/views/                  Hall / Game / Categories / Settings
  src/panels/                 背景 / 封面 / 详情 / 匹配 / 转区 / 资料源 / Steam / 获取 / 翻译
  src/styles/                 element-plus.css（按需引的 theme-chalk，18 KB）
                              + tokens.css（语义令牌 + 契约标记）+ layout.css（v1 迁移）
                              + themes/*.tokens.css + themes/*.skin.css + element.css（--el-* 桥接）
gl/web/v2/                    构建产物（入库）：index.html / overlay.html / bundle/ / build-info.json
tools/baselines/              主题截图指纹（theme-baseline.json，25 张；PNG 本体在 _sandbox/ 不入库）
```

## 主题系统

- 唯一真相：`src/styles/tokens.css` 里 `@contract` 标记的 `:root`（27 个语义令牌）。
- 每套主题两个文件：`*.tokens.css`（深 + 浅两个块，必须补齐全部令牌）+
  `*.skin.css`（≤80 行、选择器必须限定在自己的 `[data-style="…"]` 下，只放结构性签名）。
- 根属性：`<html data-style="aurora|gallery|screening|shelf" data-theme="dark|light" data-palette="…">`。
  `data-theme` 保留 v1 语义（dark / light）—— e2e 的浅色判据读的就是它；风格走 `data-style`。
- Element Plus 通过 `--el-*` 变量桥接语义令牌（`src/styles/element.css`），四套主题自动跟随。

### 主题截图基线（P8.1）

`tools/visual.py` 跑完既有判据后进入主题矩阵：5 套配置（aurora / gallery / screening / shelf
深色 + aurora 浅色）× 5 个界面（大厅 / 游戏页 / 分类 / 设置 / 背景面板）。每张截图压成
16×10 网格平均色 + 整体亮度 / 对比度，与 `tools/baselines/theme-baseline.json` 按 ±12 比对 ——
主题改的是整块面板、文字与强调色，网格均值足够抓回归，不做逐像素比对（ADR 里的分级口径）。

截图前会注入一段 freeze CSS，三件事都是为了不抖：图片素材隐藏（`<img>` 与背景层的 CSS background，
素材加载与否归封面 / 缩略图判据管，主题基线不该受网络影响；背景的暗化 / 渐晕层留着，那是主题本身）、
动画与过渡停掉（Ken Burns 与环形过渡本来就会让两帧不同）、提示条藏掉（切主题正好会弹一条）。

切主题走的是设置页那两个下拉（用户的路径），风格与明暗**分两次下发、各自等生效**：
挤在同一个 tick 里发时桥接偶尔只落一半（实测过一次「风格换了、明暗没换」，
那次录出来的 5 张整列是错的）。录基线时切不过去的那套主题直接跳过、不写进基线，
汇总里会点名 —— 宁可少一行，也不要一行假的。

重录基线（改了界面之后要跑，顺手人眼过一遍 `_sandbox/theme-shots/` 里的 25 张）：

```powershell
$env:VISUAL_UPDATE_THEME_BASELINE="1"; python tools\visual.py
```

### 其它页面的控件迁移清单（下一批）

盘点方式：数 `frontend/src/**/*.vue` 里剩下的 `<button>` / `<input>` / `<select>`
（`v-for` 算一处），再与 `tools/e2e.py` / `visual.py` / `snap.py` / `theme_probe.py` /
`vntext_probe.py` 里 `getElementById(...)` 的用法对照。盘点脚本是一次性的，留在 `_sandbox/`。

| 文件 | 剩余原生控件 | 其中探针按原生语义用的 |
| --- | --- | --- |
| `App.vue` | 1 按钮 | — |
| `components/AppModal.vue` | 1 输入 + 3 按钮 | `#modalInput`（写 `.value`）、`#modalOk`（点击） |
| `components/ToolbarBar.vue` | 1 输入 + 10 按钮 | `#btnSettings`（`classList` + 点击） |
| `views/CategoriesView.vue` | 24 按钮 + 2 输入 + 2 下拉 | `#catName`（写 `.value`）、`#catNew` / `#catSave`（点击） |
| `views/GameView.vue` | 20 按钮 | `#btnBack`（`.hidden`）、`#btnBackgrounds` / `#btnVntext` / `#btnMore`（点击） |
| `views/HallView.vue` | 8 按钮 | `#scopePick` / `#scopeClear`（点击、`.hidden`） |
| `panels/MediaPanels.vue` | 20 按钮 + 3 输入 + 2 下拉 | `#bgZoom` / `#matchQuery`（读写 `.value`）、`#locProfile`（`.options`）、`#locSwitch`（`.click()`） |
| `panels/SourcePanels.vue` | 21 按钮 + 10 输入 + 1 下拉 | `#getSiteName` / `#getSiteUrl`（写 `.value`）、`#getWatch`（`.checked`）、`#getSiteSave` / `#getAddSite`（点击） |
| `panels/VntextPanel.vue` | 16 按钮 + 2 输入 | `#vnClose`（点击） |
| `overlay/OverlayApp.vue` | 7 按钮 | —（悬浮窗是独立入口，换组件要把它的小包也带上组件库，先不动） |
| `views/SettingsView.vue` | 7 下拉 + 2 原生开关 + 7 复合控件 | `#setTransProvider`（`.options`）、`#setProxyMode`（`.value`）、两个 `.checked` 开关 |

三条规则（都由上面的盘点推出来，P8.1/P8.2 各踩过一次）：

1. **探针会写 `.value` 的输入框**（`#modalInput` / `#catName` / `#getSiteName` / `#getSiteUrl`）：
   换 `el-input` 之前先把处理函数改成读 DOM（`domValue(id, 兜底值)`，`SettingsView.saveProxy` 是样板），
   否则探针写进原生 input 的值不会进 Vue 状态，点「保存」什么都不会发生。
2. **探针会读 `.checked` 的开关保持原生**：`el-switch` 只维护自己的状态与 `aria-checked`，
   程序化改模型不会同步原生 input 的 `checked`（`#setProxyFallback` / `#setLocaleDefault` / `#getWatch` 都留着）。
3. **探针会读 `.options` / `.value` 的下拉框保持原生 `<select>`**，别换 `el-select`。
   只被点击的按钮可以放心换：`el-button` 渲染出来就是 `<button>`，id 与 class 都落在根节点上。

## 与计划的偏差（都写清原因）

1. **属性名**：计划里写的是 `data-theme=风格 + data-mode=明暗`；实现改成
   `data-style=风格 + data-theme=明暗`。原因：e2e 的「浅色主题生效 / 能切回深色」读
   `documentElement.dataset.theme`，冻结测试面优先。
2. **Element Plus 的覆盖面**：库已全局注册、`--el-*` 桥接就位，当前实际渲染用到的是
   工具条与窗口按钮的 `el-tooltip`；P8.1 起改成**按需引入**（`src/core/element.ts` 是清单），
   并把设置页的 7 个开关、3 个滑杆、19 个按钮、8 个文本框换成
   `el-switch` / `el-slider` / `el-button` / `el-input`（P8.2）。
   剩下的只有下拉框与自绘复合控件（`set-tab` / `theme-card` / `palette-chip` / `menu-row` / `vn-build`）——
   4 个下拉是探针直接读 `.value` / `.options` 的，复合控件换成组件库只有损失。
   后续动其它页面时按同一原则：先看 `tools/e2e.py` 读不读这个节点的原生语义。
3. **主页布局默认值**：新装用户默认「大图 + 侧列表」（`hall_layout` 为 `list`）；
   老用户已存的值不动（现有真实数据是 `flat`，所以升级后仍是平铺横滑）。
4. **探针的前置条件**：`tools/e2e.py` 与 `tools/visual.py` 各加了 6 行，在环形判据前
   显式 `#setHallLayout → ring`。只声明了被测布局，**判据一个字没改**（v1 前端上同样成立）。
5. **产物体积**：`gl/web/v2` 未压缩 1561 KB（计划上限 1500 KB，超 4%），
   大头是 Element Plus 的 `theme-chalk`（约 430 KB CSS）。→ **P8.1 已解决**：改成按需引入后
   整棵产物 430 KB（组件库 CSS 18 KB），JS 也顺带从 1.16 MB 降到 339 KB；
   P8.2 加上按钮与输入框两份 CSS 后是 485 KB（组件库 CSS 49 KB），仍是上限的三分之一。
6. **主题截图基线**：计划里的「深色 4 套 × 5 界面 + 浅色默认主题 5 张」首版没生成，
   → **P8.1 已落地**（见上文「主题截图基线」）。基线只存指纹不存图片：25 张 PNG 入库要好几 MB，
   指纹 JSON 只有 183 KB，PNG 本身留在 `_sandbox/theme-shots/`（已忽略）供人眼复核。
7. **主题截图会隐藏图片素材**：这是刻意的 —— `<img>` 与背景层的 CSS background 都会藏起来，
   素材加载与否归 `visual.py` 的封面 / 缩略图判据管，截图基线只判主题本身。
   不这么做，任何一次网络抖动都会变成「主题回归」。
8. **`hall_layout` 默认值**：偏差 3 说的「新装用户默认 list」这次才真的落到
   `config.DEFAULT_SETTINGS` 里（首版只改了前端兜底，后端默认仍是 ring）；
   同时把 v2 新增的 `theme`（风格键）补进默认设置。

## 怎么跑

```powershell
# 构建前端（改了 frontend/ 之后必须跑，否则 check_frontend_build 会红）
cd frontend; npm ci; npm run build

# 离线检查（14 项，纯 Python，CI 主 job 用这个）
python tools\checks\run_all.py

# 真机验收（P8.9 删 v1 后不再需要 AURORA_FRONTEND，入口固定 /v2/index.html）
.venv\Scripts\python.exe tools\e2e.py
.venv\Scripts\python.exe tools\visual.py

# 主题基线重录（改了界面之后）+ 汇总
$env:VISUAL_UPDATE_THEME_BASELINE="1"; .venv\Scripts\python.exe tools\visual.py
.venv\Scripts\python.exe tools\visual_summary.py

# 回退：P8.9 之后没有运行期开关，只能 git 回滚（见 ADR-0014）
```

`AURORA_DEV_URL=http://localhost:5173` 可以让主窗直接加载 Vite dev server（热更新）。

## 主题外观重构（P8.4，已落地）

按 `docs/frontend-ux-feedback.md` 第 2 条那条「区分度」反馈与四张参考图，
把示例页里的四类签名搬进了应用皮肤。做法与结果：

| 签名 | gallery | screening | shelf | aurora |
| --- | --- | --- | --- | --- |
| 背景处理 | 壁纸去饱和（`grayscale(.62)`）+ 冷灰洗色 → 「夜里的展墙」 | `sepia+brightness(.66)` 压成暖黑轮廓 + 琥珀光锥 | `sepia(.42) brightness(1.14)` 暖纸 + 3px 纸纹 + 木色罩 | 提饱和 + 青紫双光斑（`mix-blend-mode: screen`） |
| 排印 | 衬线（Times/Songti）；元数据大写宽字距 | Bahnschrift 窄体；时间码琥珀 | 楷体 + 衬线（卡片目录 / 手写） | 无衬线；标签用极光青 |
| 分隔与框架 | 元数据上方一条墨色短线；底栏墨线 | 元数据上方一条琥珀细线 | 黄铜基线 + 一排平刻度 | 薄玻璃底栏 + 发丝线 |
| 封面呈现 | 方角 + 1px 外框（裱起来的印刷品），无投影 | 焦点那本带外发光（「正在放映」） | 立在架上：底边黄铜线 + 焦点上抬 4px | 14px 圆角 + 极光描边 |
| 控件 | 直角 | 实色琥珀 | 实色黄铜 + 2px 圆角 | 极光渐变（唯一保留渐变的主 CTA） |

支撑这些签名的三件基础设施改动：

1. **DOM 结构性钩子**：`data-slot="title|meta|desc|cover|cover-art|cover-frame|tile|row|row-time|rail|rail-title|rail-hint|card|hero|hero-label|actions|play"`，
   只加属性，**不动几何、不动 id**（92 个探针 id 与环形几何仍是冻结面）。
2. **契约放宽**：`check_theme_contract.py` 与 `themes.spec.ts` 的皮肤上限 80 → **200 行**，
   仍然要求「选择器以 `[data-style="…"]` 开头」；「不许改布局通用规则」这条不变。
3. **色温分层**（区分度的主杠杆，改的是主题自己的令牌）：深色四套的
   `--s-base/--s-panel/--s-elevated/--ramp-s/--s-floor` 分别是
   极光深蓝黑（最薄，68%）/ 画廊冷灰（最实，92%）/ 放映厅暖黑（94%）/ 收藏架暖纸（90%，最亮）。

**区分度实测**（`tools/visual.py` 的度量，深色四套两两平均色差，目标 ≥ 20）：

| 迭代 | 平均值 | 说明 |
| --- | --- | --- |
| 改造前 | 8.6 | 只有强调色在变 |
| 加背景洗色 | 12.7 | 壁纸处理生效 |
| 加表面色温 | 13.8 → 16.4 | `--ramp-s` / `--s-floor` 分层 |
| 加排印 + 面板不透明度 | 19.4 → **20.4** | 衬线/窄体/楷体 + 面板 68–94% 分档 |

逐对（最高一版）：aurora–shelf 24.7、screening–shelf 30.0、gallery–screening 23.1、
aurora–gallery 16.1、gallery–shelf 14.6、aurora–screening 13.7。
参照：同一主题深/浅两态是 **173**。25 张主题矩阵重录后逐张比对 **最大偏差 0**，
ring 判据 `0/347.0`、`±16/283.2`、`32/232.5` 一字未动。

**一个真机抓到的回归**：`--s-floor` 只写进了各主题的深色块，而皮肤选择器
（`:root[data-style="x"]`）在浅色态**同样命中** —— 于是浅色态的面板变成了深色底，
深色文字压在上面（真机截图里底栏几乎是黑底黑字）。修法：四套主题的浅色块也各自声明
`--s-floor`。教训记在交接文档里：**主题令牌凡是只写在深色块的，都要问一句「浅色态呢」**。

对着 `docs/theme-demos/`（四套示例页 + 它的 README）与 `reference/` 的三张 Gal Launcher
参考截图（`gal-1-cream-paper` editorial / `gal-2-pale-pink` atelier / `gal-3-mist-blue` aurora）
逐条对了一遍应用，偏差如下。前两条本轮已改，其余需要先定方向再动皮肤：

| # | 偏差 | 证据 | 状态 |
| --- | --- | --- | --- |
| 1 | 极光玻璃还带一层轻模糊，示例页与文档口径也是「保留」 | 示例页 `aurora/style.css` 有 `backdrop-filter: blur(16px)`；应用 `--fx-blur: 30px` | ✅ 本轮去掉（应用 + 示例页 + 两份文档一起改） |
| 2 | 「常驻背景图」只在示例页里演示过，应用里根本没实现 | 应用里只有「每游戏一张」的本地背景（`pick_local_background`），没有全局常驻键 | ✅ 本轮实现（只支持一张） |
| 3 | 模糊口径 demo 与 app 不一致 | demo 说「只有 aurora 模糊」，应用里 screening 14px、shelf 8px 也模糊（gallery 0） | ⏳ **已拍板：四套一律归零**（2026-09-23，待执行）——但注意第 11 条反馈要极光把模糊**找回来**，这两条要一起做，见 P8.8 |
| 4 | v2 的扁平取向只落在示例页，没进应用 | demo 的按钮/面板：渐变 / 投影 / 内高光 / 模糊**全 0**；应用的 `.btn.primary` 仍是渐变 + 投影 + 内高光，面板仍吃 `--fx-panel-shadow` | 🔁 P8.7 关掉大半（圆角 / 投影 / 玻璃棱边已进令牌，画廊零投影、放映厅方正）；剩下的按钮渐变 = 反馈第 12 条，下一轮 |
| 5 | 四套主题只差配色，区分度不足 | `visual.py` 新口径：深色四套两两平均色差 **8.6**，而深/浅两态是 **193**（目标 ≥ 20） | ✅ 已关闭：P8.4 做到 **20.4**，P8.6 起判红，P8.7 后仍 20.2 |
| 6 | 展示字级与关键卡片没跟上示例页 | demo：封面 300×452、标题 46–54px；应用大厅走环形几何（冻结面）与更小的字级 | ⏳ **已拍板放大**（2026-09-23，待执行）：参照 `docs/images/详情页-Gal Launcher.png`，只动字号不碰几何 |
| 7 | atelier（浅粉桌面/纸片/胶带）那套意象没人用 | 四套里 gallery 与 shelf 都偏纸色，是最弱的一对（平均色差 9.7） | ⏳ 下一轮（2026-09-23 拍板「可尝试」）：先出小样再决定是改造 shelf 还是新增第 5 套 |

**要动的话，代价在守卫上**：现在主题皮肤被钉在「≤80 行 + 选择器必须挂在自己的
`[data-style=…]` 下 + 不许碰布局通用规则」（`check_theme_contract.py` 与 `themes.spec.ts`）。
示例页里的排印 / 分隔线 / 封面呈现 / 背景处理这四类签名，靠现有令牌改不动 ——
要么放宽到 200 行量级并给 DOM 加 `data-slot` 这类结构性钩子（不改几何、不改 id），
要么只做「扁平化 + 面板按钮统一」这一层（不碰排印与几何，风险最小）。

**本轮只做了「计量」，没动皮肤**：`visual.py` 的主题段现在会算「深色四套两两平均色差」
并写进报告与汇总（目标 ≥ 20，只报数不判红），改皮肤时就有把尺子；
`docs/frontend-ux-feedback.md` 第 2 条那张表可以直接对着看。

---

## 续做（P8.5 / P8.6：第二、三轮体验反馈）

使用者 2026-09-23 又提了四条（第 5–8 条，都是布局 / 交互层面），加上夜里发现的
一条对比度遗留。逐条记录在 [`../frontend-ux-feedback.md`](../frontend-ux-feedback.md)，
这里只留交付口径。

### P8.5（2026-09-23）：侧列表与详情页动作

- **右栏压住底栏 / 行内挤在一起 / 滚不动**：右栏 300 → 264px、底部让位 74 → 112px；
  行改 `40px minmax(0,1fr) auto` + 包装层 `min-width: 0`；口径按使用者意见定成
  「滚轮照旧切当前游戏，切完侧栏自己跟上；浏览侧栏靠拖滑动条」，
  于是加了 `watch([state.focus, layout])` 的 `scrollIntoView({block:"nearest"})`，
  行加了 hover / active 反馈。
- **真凶是环形视口盖住侧栏**：列表布局下 `#hallViewport` 仍然 `display:block` 铺满大厅、
  DOM 顺序又压在 `.hall-list-body` 之后，把真实鼠标的 hover / click / 拖动**全吃了**
  （合成事件绕过命中测试，所以前两版探针全绿）。修法一行：
  `#hall.hall-list .hall-viewport { pointer-events: none }`。
  **教训**：真机行为要用真鼠标 + `elementsFromPoint` 验。
- **详情页「…」掉到第二行**：`.game-actions` 改 `nowrap` + 收紧内边距。

### P8.6（2026-09-23）：反馈收尾 + 判红 + 工具加固

| 事项 | 位置 | 结果 |
| --- | --- | --- |
| 「导入游戏」不再二选一 | `views/HallView.vue`（删 `#addMenu`）、`features/hall/ring.ts`（钩子改名 `onAdd`）、`core/shell.ts` / `core/store.ts`（去掉 `menus.add`） | 末尾方块 / 侧列表行 / 环上 Enter 都直接 `importGames()`；`#addMenu` 的 id、CSS、`add:open` 事件一起清掉；前端测试面快照重生成（97 个 id，其中 `addMenu` 只留一条「反向断言」豁免） |
| 窗口按钮贴右缘 + 两个大厅入口进顶部栏 | `components/ToolbarBar.vue`（新增 `.toolbar-right`、搬 `#btnGetGames` / `#scopePill`）、`styles/layout.css`（`#toolbar` 右缩进 5px、`.scope-pill` 纯图标、菜单按 rect 定位） | 关闭按钮右缘距窗口右边 **8px**（含最小窗口 1040）；排序 / 范围菜单不再吃写死的 `right`，改 `placeMenu()` 贴按钮；`#scopeLabel` 留在按钮里当 `sr-only` 文字，老判据一字未改 |
| 提示条不再压顶部内容 | `styles/layout.css` 的 `#toast` | `top: 82px` → `bottom: 150px`（画面下方居中 + `max-width: min(620px, 62vw)`）；三种界面都量过不压文字 |
| 区分度判红 | `tools/visual.py` 的 `theme_spread()` / 主题段 | 目标 ≥ 20，低于目标进 `failed`（皮肤已到位：20.4） |
| `contrast.py` 抓错窗口 | `tools/contrast.py` | 采样点遮挡检测（`WindowFromPoint` + 重试置顶）+ `tainted` 与失败分开报 + 每条带 `elementsFromPoint` 命中元素 |
| 抓屏不再怕遮挡 | `tools/_common.py` 的 `print_window()`、`tools/visual.py` 的 `capture()` | 真机截图改成「先让窗口自绘（`PrintWindow` + `PW_RENDERFULLCONTENT`），自绘出黑帧再退回抓屏」—— 颜色与抓屏差 ~1/255，但别人压在上面也抓得对 |

**真机验收（2026-09-23，v2）**：

| 门 | 结果 |
| --- | --- |
| `tools/e2e.py`（v2） | **96/96 passed, 0 skipped**（新增「窗口按钮贴右缘 + 两个大厅入口在顶部栏内」；「末尾方块直接进本地导入」；转区提示条的几何并进原判据） |
| `tools/visual.py`（v2，离线） | 主题矩阵 **25/25 在容差内（最大偏差 0）**、区分度 **20.4**（目标 ≥ 20，判红已开）、ring 判据 `0/347.0`、`±16/283.2`、`32/232.5`、`errors=[]` |
| `tools/contrast.py`（真机，网络正常） | **32/32 达标**（最低 6.55，shelf-dark 设置页说明文字），`tainted` 0；gallery 浅色态游戏页 1.06 → **15.57**、1.04 → **18.54** |
| `tools/checks/run_all.py` | **14/14** |
| `python -m pytest` | 全绿 |
| `npm run typecheck` / `npm run test` | 通过 / 37 passed |
| 产物体积 | `gl/web/v2` 未压缩 496 KB / 3 js + 3 css |

**两个真机坑（这轮新踩，已写进交接文档）**：

1. **主题矩阵的两条截图路径不通用**：离线模式（`VISUAL_OFFLINE=1`，库里的游戏没有
   Steam 元数据）与联网模式（`add_by_path` 自动搜到中文名 / 厂商 / 简介）画出来的
   游戏页不是同一个界面 —— 录基线用离线、复跑用联网时，游戏页整整一格对不上
   （实测 `aurora-dark-game` 网格[1,7] 差 69）。**录与跑必须同一模式。**
2. **`dblclick` 封面会启动游戏**：主题矩阵原来用双击进游戏页，等于每录一轮就把沙盒里的
   `ping.exe` 副本启动五次 —— 游戏页多一条「运行中 · 00:00」徽标、底栏多一行游玩时长，
  前后两次跑出来的指纹自然不一样。改成单击（只进页、不启动）后稳定。
   同一处也顺手改了 `contrast.py`。

---

## 续做（P8.7：主题签名铺到主页之外 + 方正语言统一）

第三轮反馈（[`../frontend-ux-feedback.md`](../frontend-ux-feedback.md) 第 9 条）指出：
四套主题的签名单只落在主页，书架页 / 设置页 / 详情页 / 面板还是同一张脸；
而且放映厅、画廊在主页上明明是**方正、棱角分明**的，一到顶部栏、按钮、输入框又圆回去。

### 根因：几何没进令牌

P8.4 只加了 `[data-slot]` 钩子，且只加在大厅与游戏页；更要紧的是 `layout.css` 里
**90 多处圆角是写死的数字**，令牌 `--r-sm/md/lg` 只盖到 `.glass` 与 Element Plus 桥接 ——
于是画廊把 `--r-sm` 设成 1px 也没用，顶部栏 22px、菜单 18px、sheet 26px 照旧。

### 三层收口

1. **令牌**：契约补齐 `--r-xs` / `--r-xl` / `--r-pill`（连原有三个共六档），四套主题各一档：

   | 主题 | xs / sm / md / lg / xl / pill | 语言 |
   | --- | --- | --- |
   | 极光玻璃 | 8 / 11 / 16 / 22 / 26 / 999 | 圆角 + 玻璃 |
   | 收藏架 | 2 / 2 / 4 / 4 / 5 / 3 | 纸角 + 黄铜 |
   | 夜间放映厅 | 2 / 3 / 3 / 4 / 5 / 2 | 方正 |
   | 展签式画廊 | 1 / 1 / 1 / 1 / 1 / 1 | 直角 |

2. **共享布局层改用令牌**：`layout.css`（顶部栏、搜索框、图标 / 窗口按钮、菜单、sheet、
   弹窗、设置页两栏、分类两栏、缩略图、滑杆、开关、toast…）、`app.css`（强调色胶囊、
   主题卡、站点胶囊、大厅行）、`element.css`（`--el-border-radius-*`、开关与滑杆）。
   投影同样归位：`.glass` 读 `--fx-panel-shadow`（画廊 `none`），缩略图读
   `--fx-cover-shadow`，玻璃棱边光在两个方正主题里关掉。

3. **钩子补到其余页面**：书架页 `nav / nav-row / nav-label / tile-title / tile-meta /
   bar / section-title`；设置页 `page-head / page-title / nav / nav-row / surface /
   section-title / note / theme-card / row`；面板与详情页 `sheet / sheet-head / thumb /
   thumb-label`；弹窗 `modal / modal-title`；顶部栏 `toolbar / brand / search / switch / win`。
   皮肤只写线、排印、材质，几何一律交给令牌。

顺带修掉一处 P8.4 的误伤：分类卡的名字原来挂的是 `data-slot="title"`，
于是画廊 / 放映厅把 34px 的衬线**展示标题**套到了卡片小字上，现在拆成 `tile-title`。

### 验收（2026-09-23，v2）

| 门 | 结果 |
| --- | --- |
| 主题矩阵（离线，25 张） | 重录后复跑 **25/25 在容差内（最大偏差 0）**；ring 判据 `0/347.0`、`±16/283.2`、`32/232.5` 不变 |
| 区分度 | **20.2**（目标 ≥ 20） |
| `tools/e2e.py` | **96/96 passed, 0 skipped** |
| `tools/contrast.py` | **32/32 达标**，`tainted` 0（最低 6.56） |
| `tools/checks/run_all.py` | **14/14**（主题契约新增「共享层圆角必须走令牌」守卫） |
| `python -m pytest` / `npm run typecheck` / `npm run test` | 全绿 / 通过 / 37 passed |
| 产物体积 | `gl/web/v2` 未压缩 503 KB（3 js + 3 css + build-info） |

---

## P8.8 主题二轮（使用者 2026-09-23 晚拍板；**代码已落地，真机验收待跑**）

> 拍板原文、两条新的实机发现（画廊饱和度 / 极光毛玻璃）见
> [`../frontend-ux-feedback.md`](../frontend-ux-feedback.md) 的「第四轮」。
> 逐条做法与验收在 [`../handover-p8-frontend-v2.md`](../handover-p8-frontend-v2.md) 第 5 节。
>
> **落地情况（2026-09-23 晚补）**：「下一批」六项全部落到代码并重建进 `gl/web/v2/` 产物 ——
> 模糊归零 / 字号放大 / 画廊饱和度回补 / 极光恢复毛玻璃 / 参考图两块 / 删 v1 + 令牌值域守卫。
> 离线门全绿；**主题矩阵重录与 `contrast` 尚未跑**（需桌面会话，见下面「验收状态」）。

| 批次 | 事项 | 状态 | 关键验收 |
| --- | --- | --- | --- |
| 下一批 | 四套主题模糊归零（`screening` / `shelf` 的 `--fx-blur: 0`） | ✅ 已落地 | 产物已校验；矩阵重录后偏差 0、`contrast` 32/32 ⏳ |
| 下一批 | 大厅页 / 详情页字号放大（对齐 `docs/images/详情页-Gal Launcher.png` 的「文字列 ≈ 封面」配比） | ✅ 已落地 | 产物已校验（h1 40 / `#gTitle` 46 / meta·desc 15）；DOM rect 面积比 1:1 ±15% ⏳ |
| 下一批 | 画廊背景饱和度回补（`grayscale(0.62) → 0.3` + `saturate(1.04)`） | ✅ 已落地 | 产物已校验；矩阵重录、区分度 ≥ 20 ⏳ |
| 下一批 | 极光把毛玻璃找回来（`--fx-blur: 0 → 20px`，保留 `--s-floor` 与细边） | ✅ 已落地 | 产物已校验；**`contrast` 32/32 是硬门槛** ⏳ |
| 下一批 | 参考图没用上的两块：画廊「标题压画面」（`#hall.hall-list [data-slot=hero]::before` 局部遮罩）、放映厅「节目单时间轴」（`hall-side` 竖刻度 + 时间码） | ✅ 已落地 | 矩阵重录 + 使用者实机 ⏳ |
| 下一批 | 删 v1（`gl/web/*.js` + `gl/web/app/**`） | ✅ 已删（ADR-0014） | `run_all` 14/14、`pytest` 127 passed ✅ |
| 下一批 | 主题令牌「值域」守卫（`--s-floor` 不透明度、`--fx-blur`、`--r-*`） | ✅ 已加 | 故意违规实测变红（4 种）✅ |
| 下一轮 | 「开始游戏」按钮四套风格化（反馈第 12 条） | ✅ 已落地（P8.10，见下） | 画廊 / 放映厅 / 收藏架的 `.btn.play` computed `background-image: none` ✅ 产物已校验 |
| 下一轮 | 收藏架引入 Atelier 语言（先小样，再决定改造还是新增第 5 套） | 🟡 小样已出（P8.11，见下） | 区分度不低于 20（现在 gallery–shelf 14.6）——待真机实测 |
| 搁置 | 悬浮窗跟主题（使用者暂不做） | ⏸ 搁置 | — |

### 验收状态（2026-09-23 晚）

| 门 | 结果 |
| --- | --- |
| `run_all` | **14/14**（主题契约新增值域守卫；打包清单只剩 `v2/`；前端构建指纹 `e676c486bcef`） |
| `pytest` / `typecheck` / `vitest` | **127 passed** / 通过 / **38 passed** |
| 产物级校验 | `--fx-blur` 20px（极光 ×2）+ 0px（其余 ×7）、`grayscale .3/.26`、字号 40/46/15 均在 `gl/web/v2/bundle/runtime-dom-*.css` |
| 主题矩阵重录（`tools/visual.py`） | ⏳ 待跑（基线仍停在 P8.7 的 13:26，比 P8.8 样式改动早，必须重录） |
| `tools/contrast.py` | ⏳ 待跑（32 个采样点） |
| `tools/e2e.py` | ⏳ 待跑（需 Steam / 网络） |

**执行顺序的建议**：下一批里前 5 条都是「改皮肤 / 改字号」，会一起动主题矩阵，
所以**攒成一次改动 + 一次基线重录 + 一次 contrast** 最省事；删 v1 与令牌值域守卫
是纯工程项，可以和它们并行，互不影响。

**一条被推翻的「遗留」**：2026-09-23 夜里的 `gallery-light 游戏页 1.06 / 1.04`
不是主题问题 —— 那张 `_sandbox/contrast-shots/gallery-light-game.png` 里，
使用者正跑着的 galgame 窗口与翻译悬浮窗压住了采样带，量到的是别人的近黑底。
旁证：同轮其余 30 点底色正常（浅色态 228–253），而 gallery 浅色态的兜底用的是
白色 `--scrim-rgb`，算不出近黑。因此**没有**给游戏页加第二层浅色兜底，
只把工具补强成「被盖住就报没测到、退出码非 0」。

---

## P8.9 删 v1（2026-09-23 晚）

[ADR-0014](../adr/ADR-0014-drop-v1-frontend.md)：v2 连续多轮全绿之后，把并行的 v1
（无构建 ES 模块）整个删掉，入口固定 `/v2/index.html`。

- **删了 22 个文件**：`gl/web/index.html`、`overlay.html`、`app.css`、`app.js`、`gl/web/app/**`。
- **打包清单收成一套**：`WEB_FILES = ()`、`WEB_MODULE_DIRS = ("v2",)`。
- **守卫扫描面从 `gl/web/**` 换成 `frontend/src`**：`tools/checks/common.py` 新增
  `frontend_sources()`，主窗 / 悬浮窗分开取；`check_contract` / `update_contract` /
  `check_layers` / `check_bridge` 全部改用它。分层守卫的「不许绕过 `call()`」现在是
  「主窗源码里只有 `core/api.ts` 能出现 `pywebview`」（`main.ts` 的探活改为复用 `bridge()`）。
- **契约快照重算**：前端调用点 100（v1）→ **103**（v2 主窗），新增 5 个（常驻背景 3 个 +
  术语表 1 个 + 背景模式 1 个），移走 2 个（`get_hook_search_status` / `open_textractor_page`
  这两个 v1 有、v2 没有）。
- **架构基线登记搬家**：`baseline.json` 的 `superseded_by` 记 22 条 v1 → v2 映射。

验收：`run_all` **14/14**、`pytest` **127 passed**、`typecheck` 通过、`vitest` **38 passed**。

---

## P8.10 主 CTA 四套风格化（2026-09-23 晚）

反馈第 12 条：`.btn.play` 只有三套有覆盖，**画廊完全没覆盖**（还在用 layout.css 的蓝色渐变，
跟它「无渐变、只有线」的语言自相矛盾），而 `.btn.primary`（创建分类 / 保存并测试 / 确定）
四套都是渐变。四套各给一套主 CTA 语言：

| 主题 | 落地 |
| --- | --- |
| 展签式画廊 | `background: var(--a-main)` 实色 + 直角（令牌 1px）+ `inset 0 0 0 1px` 白 34% 内框；渐变、投影、棱边全清；`.running` 退回透明 + 细线 |
| 夜间放映厅 | 琥珀实色 + `tabular-nums` + `letter-spacing: 0.08em`（时间码那一档）；`:active` 加深并加一圈琥珀辉光 |
| 收藏架 | 黄铜实色 + **压印**（内阴影：上缘白 26% + 下缘深棕 45%），外投影清零；`:active` 内阴影加深 |
| 极光玻璃 | 唯一保留渐变；`box-shadow` 从两层收成一层（`0 8px 20px -12px`，极光色 65%） |

**顺带修掉两处守卫口径不一致**（这一轮才暴露）：

1. `themes.spec.ts` 数皮肤**总行数**、Python 守卫数**非空行** —— 两个「镜像」口径不同，
   放映厅加到 201 总行时 JS 红、Python 绿。现在 JS 对齐成非空行（Python 是权威）。
2. `frontend/scripts/build-info.mjs` 与 `tools/checks/check_frontend_build.py`
   现在都跳过 Vite 转译 TS 配置留下的 `vite.config.ts.timestamp-*.mjs`。
   正常 Vite 会自删；删不掉时（权限 / 沙箱）会污染指纹（实测源文件数 62 → 63，
   `check_frontend_build` 直接红）。`.gitignore` 也加了这条。

验收：产物里画廊 / 放映厅 / 收藏架是实色、只有极光是渐变（已核对构建后的 CSS）；
`run_all` **14/14**、`pytest` **127 passed**、`typecheck` 通过、`vitest` **38 passed**。
真机主题矩阵重录待跑（与 P8.8 那批一起录一次即可）。

---

## P8.11 Atelier 小样（2026-09-23 晚）

反馈第 4 项要「先出一版小样，量一次区分度，再决定是改造收藏架还是新增第 5 套」。
按本项目挑方向的惯例（`theme-demos/`），小样做成一张**独立静态示例页**，
**没有动应用里的收藏架** —— 因为方向还没定，先改就等于提前选了「改造」那条路。

`docs/theme-demos/atelier/`（`index.html` 4.7 KB + `style.css` 9.4 KB）：

| 元素 | 做法 |
| --- | --- |
| 浅粉工作台 | 玫瑰色桌面 + 极淡的**切割垫网格**（两个方向的 `repeating-linear-gradient`），纯 CSS 不用位图 |
| 奶油纸片 | 纸面卡 + 玫红细边，整体歪 -0.35°；不靠投影立起来（延续 v2/v3 的扁平取向） |
| 和纸胶带 | 半透明暖粉条 + 白细竖纹，`clip-path` 做两端撕口，左右两段角度不同 |
| 剪贴板 | 封面当「夹在板上的照片」：纸背 + 上缘一小段胶带，`nth-child` 交替 ±1° 错落 |
| 排印 / 按钮 | 楷体 + 衬线；主按钮玫红实色 50px、无渐变无投影（与另四套同一条扁平规则） |

入口页多了一张 `Candidate` 卡；`README.md` 补了 Atelier 小节与对照表的一行。
静态一致性（本地引用是否存在、CSS 括号配平、关键结构齐不齐）由
`_sandbox/verify_demos_static.py` 离线校验：**五个页面全过**。

**还差的一步（需要真机）**：区分度实测。`visual.py` 重录后看 `visual_summary.py` 里
Atelier 与收藏架的色差（现在 gallery–shelf 14.6，目标线 20）：
够 → 当第 5 套（注册 `core/theme.ts` 的 `THEMES`、`visual.py` 的 `THEME_MATRIX`、
`check_theme_contract.py`、`themes.spec.ts`，主题矩阵 25 → 30 张）；
不够 → 改成「改造收藏架」。`preview/` 里也还没有它的预览图（生成预览要真机渲染）。

---

## 还没做的（下一步）

### P8.11 收尾（2026-09-23 深夜）：真机门补跑 + 两个真机 bug

上一轮把「真机门待跑」写进了交接，这一轮在交互桌面会话里补齐，顺手抓到两个**只有真机
才暴露**的问题（离线门全绿，`e2e` / 像素复测才发现）：

| 项 | 内容 |
| --- | --- |
| 主题矩阵重录 | `VISUAL_OFFLINE=1` 重录 → 复跑 **25/25、逐张偏差 0**；区分度 **20.2**（目标 ≥ 20）；新基线 `tools/baselines/theme-baseline.json` |
| `contrast` / `e2e` | **32/32（tainted 0）** / **96/96 passed, 0 skipped** |
| bug ①　画廊色块 | 布局层 `#hall::before` 把极光的深蓝黑写死，而画廊的整屏遮罩只覆盖 `#hall:not(.hall-list)` → 列表布局（v2 默认）那一块回落到极光色。浅色态实测右下一整块 lum 60、旁边 242；改成 `rgb(var(--scrim-rgb) / …)` 后 242 / 249。使用者实机反馈（反馈文档第 13 条） |
| bug ②　悬浮窗不出现 | P8.9 删 v1 时 `aurora/ui/overlay.py` 仍指向 `gl/web/overlay.html`；且 v2 产物是 ES module，`file://` 下会被拦。改成 `gl/web/v2/overlay.html` + `main.build_window()` 注入 `{server.url}/v2/overlay.html?v=…`，`check_packaging.py` 加断言防复发（`e2e` 第 85 步就是这条的判定） |
| 工具健壮性 | `guard_webview_start()`：`loaded` 超时 60s 就写日志 + 退出码 3（原来会静默挂死）；`park_cursor()`：截图前把鼠标挪出窗口（hover 高亮会让逐格比对出现假偏差，实测差 19） |

**产出**：前端指纹 `944c1119c766` / 62 个源文件，`Aurora.exe` 24.5 MB 已重建。
离线门 `run_all` 14/14、`pytest` 127 passed、`vitest` 38 passed。

### P8.13 收尾（2026-09-23 夜）：两条使用者实机反馈

两条都是「真机一眼看得见、离线门全绿」的观感问题，改动都在皮肤与令牌里：

| 项 | 内容 |
| --- | --- |
| ① 极光浅色没有毛玻璃 | 浅色块 `--ramp-s-k: 12` 把白色高光阶梯乘到 alpha 1.62 → 钳成 **1.0**，`.glass` 第一层渐变成了实心白 → `backdrop-filter` 糊了个寂寞（实测「开/关模糊」的像素差 0.03）。改 1.4（与深色 1.35 同档）、`--s-floor` 88% → 72%；底栏 `[data-slot="rail"]` 与 `.btn.glass-btn` 补上模糊（此前只有底色）。复测：设置页 0.03 → **3.75**、游戏页 0.04 → **2.74**，`contrast` 32/32 未退 |
| ② 画廊顶部没有遮罩 | 整屏冷灰罩只写 `#hall:not(.hall-list)`，列表布局的局部遮罩又长在 `[data-slot="hero"]`（盒子从 y=84 开始）→ 顶部 84px 没人盖（逐行剖面在 y=84 有台阶：深色 76.1→53.3、浅色 208.3→229.1）。整屏罩改到 `#hall`（所有布局），局部遮罩 `inset: -84px 0 0 0` 往上长到窗口顶；复测台阶消失 |

门：主题矩阵重录 **25/25 偏差 0**（区分度 20.2）、`contrast` **32/32（tainted 0）**、
`e2e` **96/96**、`run_all` 14/14、`pytest` 127 passed、`vitest` 38 passed；
前端指纹 `54fa228885ce`（62 个源文件），`Aurora.exe` 24.5 MB 已重建。

### P8.14（2026-09-23 夜）：主页交互与浅色画廊

使用者这一轮提了四条（反馈文档第 16–19 条），本轮做前三条 + 第四条的 a 半：

| 项 | 内容 |
| --- | --- |
| ① 侧栏长名字压时长 | `.row-title` 是行内 `<span>`，`overflow`/`text-overflow` 对行内盒无效 → 名字既不截断也不换行，直接压在 `auto` 宽的时长列上。改成块级、最多两行（`-webkit-line-clamp: 2`）、长西文 `overflow-wrap: anywhere`；时长列 `white-space: nowrap` |
| ② 浅色画廊过亮 | 先量四套浅色的整屏平均亮度定标（极光 200.7 / 画廊 **215.8** / 放映厅 203.4 / 收藏架 204.9），逐格差分定位到 hero 局部遮罩（94% 白）+ 整屏白罩；降到 0.72/0.52/0.24 与 0.74/0.44/0.20/0.40，并把 `--scrim-rgb`、`--s-base`、`--s-panel`、`--s-floor` 各降一档 → 复测 **207.1**（+2.5…+6.8 于另三套） |
| ③ 删「双击封面启动」 | 侧栏 `@dblclick`、`ring.ts` 的 dblclick、提示条里的「双击 启动」三处一起下掉；`e2e` 第 3.6 步从「双击封面直接启动」改写成「主页启动按钮直接启动」（切到 list → 点 `#btnHallPlay` → 断言运行徽标 → 切回 ring），前端表面快照 97 → 98 id |
| ④-a 主页启动按钮 | `#btnHallPlay` 加在大图 + 侧列表的信息列（简介下方，`data-slot="hero-actions"`），样式 `.hall-label-actions` + `.btn.play`，四套主题的主 CTA 语言自动生效 |

门：主题矩阵重录 **25/25 偏差 0**（区分度 20.2）、`contrast` **32/32（tainted 0）**、
`e2e` **96/96**、`run_all` 14/14、`pytest` 127 passed、`vitest` 38 passed；
`Aurora.exe` 24.5 MB 已重建。

**留给下一轮**（反馈第 19-b、20 条）：环形 / 横滑 / 侧列表的右键菜单
（启动 / 收藏 / 移除 / 详情），为此要删掉环形与横滑的「悬停即切换」；
Atelier 作为第 5 套主题（拍板做，工作量排到下一轮）。

### 其它还没做的

0. **视觉 / 体验反馈**：2026-09-22 的三条与 2026-09-23 的四条已全部处理完
   （证据与逐条结论见 [`../frontend-ux-feedback.md`](../frontend-ux-feedback.md)）；
   还挂着的是「主题外观重构」表里的第 3、4、6、7 条取向问题（要不要统一去模糊、
   要不要把示例页的扁平取向搬进应用、展示字级、atelier 那套意象），那些要先定方向再动皮肤。
1. 其它页面的自绘控件按同样节奏换 `el-`（大厅 / 详情 / 面板里还有一批按钮与输入框）。
   动之前先看 `tools/e2e.py` 有没有直接读写这些节点 ——
   `#setHallLayout` / `#setTheme` / `#setProxyMode` / `#setTransProvider` / `#setProxyFallback` /
   `#setLocaleDefault` / `#getWatch` / `#bgZoom` 都是探针按原生语义读的
   （`.value` / `.checked` / `.options`），换组件要么加薄壳、要么改判据（不建议）。
2. v2 稳定一个版本后，另立 ADR 决定是否删掉 v1（`gl/web/*.js` 与 `gl/web/app/`）。
3. `Aurora.exe` 每次前端改动后都要重建（`python tools\build_exe.py`）：
   入库的只有 `gl/web/v2/` 产物树，exe 本身不进仓库。
