# 交接 · P8 前端 v2 与主题外观重构（P8.4）

> 写给下一个接手的人。总览看 [`handover.md`](handover.md)，
> 交付细节看 [`architecture/p8-frontend-v2.md`](architecture/p8-frontend-v2.md)，
> 体验反馈与验收口径看 [`frontend-ux-feedback.md`](frontend-ux-feedback.md)。
> 最后更新：2026-09-23 深夜（**P8.11：真机门全部补跑通过 + 修掉两个真机才暴露的 bug**）。
> 三道真机门现在都是绿的：主题矩阵重录 **25/25（偏差 0）**、`contrast` **32/32**、
> `e2e` **96/96** —— 见第 2 节；两个 bug 与三个工具的坑见第 1、4 节。

## 1. 这一轮做完了什么

按「四套主题区分度不足」那条反馈（`frontend-ux-feedback.md` 第 2 条）把示例页里的
四类签名搬进了应用皮肤，并落地前一晚定下的两件明确要求：

| 事项 | 位置 | 状态 |
| --- | --- | --- |
| 极光玻璃去掉轻模糊 | `themes/aurora.tokens.css`（`--fx-blur: 0`）、`aurora.skin.css`（删 `backdrop-filter`）、`tokens.css`（契约默认值 0） | ✅ |
| 常驻背景图（只支持一张） | `aurora/infra/config.py`（`background_mode/background_custom/background_custom_scale`）、`aurora/ui/bridge/library.py`（5 个桥接方法 + `_set_persistent_background` 测试缝）、`BackgroundLayer.vue`、`MediaPanels.vue`（背景面板来源胶囊 + 更换/清除 + 常驻缩放） | ✅ 真机探针全绿 |
| DOM 结构性钩子 | `HallView.vue` / `GameView.vue` / `CategoriesView.vue` 的 `data-slot="…"`（只加属性，不动几何与 id） | ✅ |
| 皮肤契约放宽 | `check_theme_contract.py` / `themes.spec.ts`：皮肤 ≤80 → **≤200 行**；「选择器必须挂在自己的 `[data-style=…]` 下」不变 | ✅ |
| 四套主题签名 | `themes/*.skin.css`（背景处理 / 排印 / 分隔与框架 / 封面呈现 / 底栏）+ `themes/*.tokens.css`（底色与表面色温分层） | ✅ |
| 区分度度量 | `tools/visual.py` 的 `theme_spread()` + `visual_summary.py` 输出；目标 ≥ 20 | ✅ **20.4**（改造前 8.6） |
| P8.5 侧列表修补 | `app.css` 的 P8.5 小节（右栏 264px / 行网格 / hover 反馈）、`HallView.vue` 的 `watch([state.focus, layout])`、`#hall.hall-list .hall-viewport { pointer-events: none }` | ✅ 真鼠标探针（`_sandbox/probe_real_mouse.py`） |
| P8.6 反馈收尾 | 删 `#addMenu`（导入游戏直接进本地导入）、`#btnGetGames` / `#scopePill` 搬进顶部栏做纯图标、`#toast` 挪到画面下方、`visual.py` 区分度判红、`contrast.py` 遮挡检测 | ✅ 见下面第 2 节 |
| P8.7 主题语言铺满全界面 | `tokens.css` 的 `--r-xs/xl/pill` + 四套 `*.tokens.css` 的圆角档位、`layout.css` / `app.css` / `element.css` 全面改用令牌、其余页面的 `data-slot` 钩子、四套 `*.skin.css` 的线 / 排印 / 材质 | ✅ 主题矩阵 25/25（偏差 0）、`e2e` 96/96、`contrast` 32/32 |
| P8.8 主题二轮（模糊归零 / 字号放大 / 画廊饱和度 / 极光毛玻璃 / 参考图两块） | `themes/*.tokens.css`、`themes/*.skin.css`、`layout.css`、`app.css` | ✅ 代码与产物已落地（2026-09-23 晚；**真机矩阵重录 / `contrast` 待跑**，见第 2、5 节） |
| P8.8-b 主题令牌值域守卫 | `tools/checks/check_theme_contract.py` 第 6 节、`themes.spec.ts` | ✅ 故意违规 4 种实测全部变红 |
| P8.9 删 v1（22 个文件 + ADR-0014 + 扫描面 / 打包清单 / 契约快照 / 基线登记同步） | `gl/web/**`、`main.py`、`tools/build_exe.py`、`tools/checks/*` | ✅ `run_all` 14/14、`pytest` 127 passed |
| P8.10 主 CTA 四套风格化（反馈第 12 条） | `themes/*.skin.css`、`themes.spec.ts`、`build-info.mjs` | ✅ 代码与产物已落地（2026-09-23 晚；真机矩阵重录待跑） |
| P8.10-b 收藏架 Atelier 语言 | — | ⏳ 未动（见第 5 节） |
| P8.11 真机门补跑 | `tools/visual.py`、`tools/contrast.py`、`tools/e2e.py` | ✅ **三道全绿**（2026-09-23 深夜：25/25 偏差 0、32/32 tainted 0、96/96） |
| P8.11-a 画廊「色块不一致」（使用者实机反馈） | `layout.css` 的 `#hall::before` | ✅ 修：整屏遮罩从写死的极光深蓝黑改成 `var(--scrim-rgb)`（见第 5 节末） |
| P8.11-b 悬浮窗不出现（`e2e` 抓到的 P8.9 回归） | `aurora/ui/overlay.py`、`main.py`、`check_packaging.py` | ✅ 修：入口从已删的 `gl/web/overlay.html` 改到 v2 + 走本地静态服务（ES module 在 `file://` 下被拦） |
| P8.11-c 真机工具静默卡死 | `tools/_common.py::guard_webview_start`、`park_cursor` | ✅ 修：`loaded` 超时快失败（退出码 3）；截图前把鼠标挪出窗口 |

## 2. 现在验证到哪一步

**P8.11（2026-09-23 深夜）—— 离线门 + 真机门全部绿**

| 门 | 结果 |
| --- | --- |
| `tools/visual.py`（主题矩阵） | ✅ **25/25，逐张最大偏差 0**；基线 17:52 重录（P8.8/P8.10 之后的样式）；区分度 **20.2**（目标 ≥ 20） |
| `tools/contrast.py` | ✅ **32/32 达标、tainted 0**（最低 6.66 对门槛 4.5）；极光恢复 20px 毛玻璃后复验通过 |
| `tools/e2e.py` | ✅ **96/96 passed, 0 skipped**（修掉悬浮窗入口之后） |
| `tools/checks/run_all.py` | ✅ **14/14**（新增「悬浮窗入口必须存在」一条断言） |
| `python -m pytest` | ✅ **127 passed** |
| `npm run typecheck` / `npm run test` | ✅ 通过 / **38 passed** |
| 产物 | ✅ `gl/web/v2` 指纹 **944c1119c766** / 62 个源文件；`Aurora.exe` 已重建（24.5 MB） |

**本轮（P8.8 + P8.9 + P8.10，2026-09-23 晚）复跑 —— 离线门全绿，真机门当时待跑**

| 门 | 结果 |
| --- | --- |
| `tools/checks/run_all.py` | ✅ **14/14**（主题契约新增「令牌值域」第 6 节；打包清单只剩 `v2/`；前端构建指纹 `d5e4a71e1dec` / 62 个源文件） |
| `python -m pytest` | ✅ **127 passed** |
| `npm run typecheck` / `npm run test` | ✅ 通过 / **38 passed**（新增 1 条值域用例） |
| 值域守卫的故意违规 | ✅ 4 种全变红（极光模糊抹 0 / 画廊偷加模糊 / 收藏架 `--s-floor` 掉 50% / 放映厅圆角档位反） |
| 产物级校验（主题值） | ✅ `gl/web/v2/bundle/runtime-dom-*.css` 里 `--fx-blur: 20px`（极光 ×2）、`0px`（其余 + 契约默认 ×7）、`grayscale(.3/.26)`、字号 40/46/15 均在位 |
| 产物级校验（主 CTA） | ✅ 画廊 `background: var(--a-main)`、放映厅 `#e9a13b`、收藏架 `#c8a24a` 都是实色，只有极光是 `linear-gradient` |
| `tools/visual.py`（主题矩阵重录） | ✅ 已补跑（17:52 重录，复跑 25/25 偏差 0） |
| `tools/contrast.py` | ✅ 已补跑（32/32，tainted 0） |
| `tools/e2e.py` | ✅ 已补跑（96/96；就是这一跑抓到悬浮窗入口那个回归） |

> **补记（P8.11）**：当时「真机门跑不了」的结论**只对了一半**。真正的现象是
> WebView2 初始化**偶发**失败（`0x8007139F`，日志一行 `WebView2 initialization failed`），
> 而工具只挂在 `window.events.loaded` 上 —— 事件不来就**永远等下去**，看起来像
> 「这个环境起不了窗口」。同一台机器、同一份代码隔十几分钟再跑就正常（实测两次），
> 现在由 `_common.guard_webview_start()` 兜底：超时 60s 就写日志 + 退出码 3。
> 会话是交互桌面（Session 1）就不再是障碍，按第 3 节直接跑即可。

**历史（P8.7 及以前，基线仍是那一版）**

| 门 | 结果 |
| --- | --- |
| `tools/visual.py` | 25/25 张与基线逐张比对**最大偏差 0**；ring 判据 `0/347.0`、`±16/283.2`、`32/232.5` 不变；区分度 **20.2**（P8.6 起低于 20 会判红） |
| `tools/e2e.py` | ✅ **96/96 passed, 0 skipped**（2026-09-23 上午，网络正常） |
| `tools/contrast.py` | ✅ **32/32 达标**，`tainted` 0（2026-09-23，真机 + 真实壁纸；最低 6.55） |
| 常驻背景探针（`_sandbox/probe_persistent_bg.py`） | 默认跟随 ✓ / 切常驻 ✓ / 缩放 ✓ / 切回 ✓ / 清除并删文件 ✓ |
| 顶部栏 / 提示条几何（`_sandbox/probe_toolbar_toast.py`） | 关闭按钮距窗口右边 **8px**、两个图标在顶部栏内且点得到、范围菜单贴按钮、提示条不压标题与底栏 |

## 3. 恢复验证的顺序（网络正常时）

> P8.11 已按这个顺序完整跑过一遍并全绿（2026-09-23 深夜）；下面第 1 步的
> 「基线必须先重录」只在**样式又改过**时才需要。

```powershell
cd C:\Users\HuHu1\Desktop\Tasks\v4.1\Aurora

# 0) 真机工具要 pywebview + Pillow。项目 .venv 已有 pywebview，Pillow 是本轮补装的：
#    .venv\Scripts\python.exe -m pip install "Pillow>=10.0"
#    （requirements.txt 里 Pillow 是「仅 tools/ 自检脚本需要」的可选项）

.venv\Scripts\python.exe tools\checks\run_all.py     # 先离线，14 项
D:\Anaconda\python.exe -m pytest -q -p no:cacheprovider `
    --basetemp="$env:TEMP\aurora-pytest"             # 127 个用例

# 1) 主题矩阵：P8.8 改过样式，基线必须先重录（离线录就离线跑，别混）
$env:VISUAL_OFFLINE="1"
$env:VISUAL_UPDATE_THEME_BASELINE="1"
.venv\Scripts\python.exe tools\visual.py
Remove-Item Env:\VISUAL_UPDATE_THEME_BASELINE
.venv\Scripts\python.exe tools\visual.py             # 复跑：期望 25/25、偏差 0
.venv\Scripts\python.exe tools\visual_summary.py     # 区分度，目标 ≥ 20

.venv\Scripts\python.exe tools\contrast.py           # 32 个采样点，硬门槛 32/32
.venv\Scripts\python.exe tools\e2e.py                # 96 项，需要 Steam

# 前端变了就要重建（产物入库）：先 npm，再 exe
cd frontend; npm run build; cd ..
.venv\Scripts\python.exe tools\build_exe.py
```

> **P8.9 起不再有 `AURORA_FRONTEND`**：入口固定 `/v2/index.html`，回退只能靠 git 回滚
> （[ADR-0014](adr/ADR-0014-drop-v1-frontend.md)）。
> 离线门用的 python 可以是任意 3.13；真机门必须有 `pywebview`（`.venv` 或 `_build\venv`）。

## 4. 这套真机工具的坑（都踩过，别再踩）

1. **桌面不再必须空着（但空了更省事）**。截图改成「先让窗口自绘
   （`_common.print_window`：`PrintWindow` + `PW_RENDERFULLCONTENT`），
   出黑帧才退回抓屏」，所以别的窗口压在 Aurora 上面也抓得到自己的界面
   （2026-09-23 之前的版本抓过整屏聊天窗口、终端窗口，还当成过主题回归）。
   仍然别让**别的程序抢焦点太久**：WebView2 被降频时，主题矩阵会报 `unready`。
2. **主题矩阵的抖动**都已处理：图片素材隐藏（`img,.bg-img`）、提示条隐藏（`#toast`）、
   缩略图占位隐藏（`.bg-item i`）、**`el-tooltip` 浮层隐藏**（`.el-popper` ——
   鼠标恰好停在按钮上就会多出一块浅色矩形）；还加了「等环形浮动收敛」与
   「抓图前确认页面到位」。录基线时切不过去的主题会**跳过不写**，不会把错帧录进去。
2.5. **进游戏页要单击，别双击**：环上双击是「启动游戏」——主题矩阵原来用双击进页，
   等于每录一轮就把沙盒游戏启动五次，游戏页多一条「运行中 · 00:00」徽标，
   前后两次跑出来自然不一样（实测差 69）。`contrast.py` 同一处也改了。
2.8. **圆角只写在令牌里，皮肤只管线与排印**（P8.7 之后的规矩）：
   共享层（`layout.css` / `app.css` / `element.css`）里出现写死的 `border-radius`
   会被主题契约守卫直接拦下 —— 因为「画廊 / 放映厅是方角、极光是圆角」这条语言
   只要有一处漏网就破功（P8.7 之前正是如此：令牌已经设成 1px，顶部栏还是 22px）。
   要新加组件时：圆角写 `var(--r-xs|sm|md|lg|xl|pill)`，投影写
   `var(--fx-panel-shadow)` / `var(--fx-cover-shadow)`，剩下交给皮肤。
   新页面要能被主题认出来，就给它挂 `data-slot="…"`（见第 4 节末尾的表）。
3. **`assets/…` 是相对页面的地址**：v2 的页面在 `/v2/` 下，任何新加的图片设置
   都要过 `fixAssetUrl()`（`core/assets.ts`）。常驻背景第一版就栽在这上面（404 → 背景不换）。
4. **改主题时两个 `set_setting` 别挤在同一个 tick**：`theme_apply()` 里风格与明暗是分两次下发、
   各自等生效，否则偶尔只落一半（会被录成错的基线）。
5. **主题令牌只写在深色块 = 浅色态也会中招**：`themes/*.tokens.css` 的选择器是
   `:root[data-style="x"]`，它**不区分深浅**；`:root[data-style="x"][data-theme="light"]`
   只是更具体的一份覆盖。P8.4 就把 `--s-floor` 只写进深色块，浅色态面板变黑底
   （真机截图里是黑底黑字），是 `snap.py` 才看出来的。加令牌时两份都要写。
6. **合成事件验不了「点得到」**：`element.click()` / `dispatchEvent` / `scrollIntoView`
   都绕过命中测试。P8.5 因此返工三次 —— 列表布局下 `#hallViewport`（环形容器）
   仍铺满大厅、压在右侧栏上，把真实鼠标的 hover / click / 拖滚动条**全吃了**，
   而所有合成探针都是绿的。**真机交互必须用真鼠标输入 + `elementsFromPoint` 复核**：
   样板见 `_sandbox/probe_real_mouse.py`（`SetCursorPos` + `mouse_event`，
   坐标用页面自报的 `window.screenX/screenY × devicePixelRatio` 换算；
   窗口若比屏幕宽，滚动条那条会落在屏幕外，先把窗口挪进来再测）。
   修法是 `#hall.hall-list .hall-viewport { pointer-events: none }`。
7. **真机工具需要「有交互桌面 + Aurora 在前台」的会话**（2026-09-23 晚实测）。
   在 agent 那种非交互上下文里跑 `visual.py`，症状是**卡住且不报错** ——
   因为 `run()` 只挂在 `window.events.loaded` 上，`loaded` 不来就永远等下去。
   这一轮排出来的三层原因，按发生顺序：

   | 现象 | 原因 | 处理 |
   | --- | --- | --- |
   | 日志只有 entry 一行，`loaded` 从不触发；`evaluate_js` 报 `Main window failed to start` | `_sandbox/visual-data/webview` 这个 **WebView2 profile 坏了**（脚本每次会 `rmtree` 重建，但坏过一次后残留会继续生效） | 删掉该 profile 目录（`rm -rf`，或整块挪走）后 `loaded` 恢复 |
   | `loaded` 来了、第一次 `capture()` 也出了图，但**整张全黑**（14 KB），随后 `evaluate_js` 挂住 | 窗口在后台被判定遮挡，WebView2 不绘制 / JS 被降频 | 需要窗口在前台。`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-features=CalculateNativeWinOcclusion` **实测无效** |
   | 同代码换成**内联 HTML**（`create_window(html=…)`）时一切正常 | 说明 WebView2 本身可用，卡的是「从本地 HTTP 服务加载页面 + 渲染」这一段 | — |

   排查用的探针留在 `_sandbox/probe_webview_diag.py`（`inline` / `server` 两种模式，
   结果写 `_sandbox/webview-diag.log`，不依赖 stdout，被强杀也能看）。
   **P8.11 修正结论**：这不是「环境起不了 WebView2」，而是**偶发失败 + 工具没超时**。
   同一台机器隔十几分钟重跑就好（已复现两次），所以现在：
   `guard_webview_start()` 盯着 `loaded`，超时 60s 就写一条能看懂的日志并**退出码 3**
   —— 不再静默挂死；`AURORA_WV_FRESH_PROFILE=1` 可以先把该工具的 profile 目录
   改名留档再启动（治「profile 坏掉」那一种）。**别再靠反复手跑猜**。

8. **截图前必须把鼠标挪出窗口**（`_common.park_cursor()`，`visual.py` / `contrast.py`
   的 `capture()` 里已经调了）。主题矩阵是逐格比对的，指针停在设置页的行 / 卡片上会留下
   hover 高亮 —— 2026-09-23 实测：`e2e` 的拖动测试把光标留在设置页，同一份基线
   `aurora-light-settings` 网格 `[8,4]` 从 `[250,251,251]` 变成 `[232,232,233]`（差 19，
   超容差 12），于是「一会儿 25/25、一会儿 24/25」。`.el-popper`（tooltip）那条早处理了，
   hover 高亮靠这一步。

9. **删了 v1 之后，凡是「按路径打开页面」的地方都要跟着改**。P8.9 只改了主窗入口，
   `aurora/ui/overlay.py` 的 `HTML_PATH` 还指着 `gl/web/overlay.html` —— 离线门全绿，
   真机上悬浮窗**直接不出现**（`data/logs/aurora.log` 里是 `overlay html missing`），
   只有 `e2e` 的第 85 步抓得到。修法是两条一起：
   `HTML_PATH = config.WEB_DIR / "v2" / "overlay.html"`，
   并且**地址交给本地静态服务**（`main.build_window()` 里
   `overlay.set_entry_url(f"{server.url}/v2/overlay.html?v=…")`）——
   v2 产物是 `<script type="module">`，`file://` 下会被浏览器按跨源规则拦掉，
   就算路径修对了也只会开出个空壳。
   守卫：`check_packaging.py` 现在会静态读 `HTML_PATH` 并断言文件存在。

10. **`contrast.py` 用真实数据目录是有意的**（要按使用者的真实壁纸采样），
   所以它会真的切主题 —— 但**改完必须落盘了再退**：存储是「去抖 + 后台写线程」，
   还原之后紧跟的 `os._exit` 会把还没写的还原丢掉。2026-09-23 实测：跑完这个工具，
   使用者的设置被留在 `gallery-light`（他原本是 `aurora-dark`），
   还得手动改回去。现在 `finally` 里还原之后会 `api._library.flush()`；
   要完全避开真实数据，就带 `CONTRAST_OFFLINE=1` 跑（用 `_sandbox/contrast-data`，
   量不到真实壁纸）。

## 5. 还没做的

**三个真机门已关闭；剩下「下一轮」两项**

| # | 事项 | 状态 |
| --- | --- | --- |
| 1 | **真机门补跑**：`visual.py` 主题矩阵重录 + `contrast.py` 32/32 + `e2e.py` 96/96 | ✅ 已完成（P8.11，2026-09-23 深夜）；基线已重录到 17:52 的样式 |
| 2 | **四套主题的「开始游戏」按钮风格化**（反馈第 12 条） | ✅ 已落地（P8.10）并已过真机矩阵；画廊实色 + 直角 + 1px 内框、放映厅琥珀实色 + 时间码字距 + 按下辉光、收藏架黄铜实色 + 内阴影压印、极光保留渐变但收敛投影；`.btn.primary` 一并收口 |
| 3 | **收藏架引入 Atelier 语言**（反馈第 4 项） | 🟡 **小样已出**（`docs/theme-demos/atelier/`，独立静态示例页，**没动应用里的收藏架**）。**新基线下的 gallery–shelf 是 16.1**（旧 14.6，目标 20）→ 按原口径仍属「不够」，要么把 Atelier 做成第 5 套（矩阵 25 → 30 张），要么真去改造收藏架；两条都要先定方向再动皮肤 |
| 4 | **悬浮窗跟主题**：`overlay/main.ts` 只挂了 app.css，没有像主窗那样调 `applyTheme()`，所以永远用 `:root` 默认令牌（极光深色）。圆角已经改成令牌（`--r-md` / `--r-xs`），真要变脸得让 Python 侧把 `theme / theme_mode` 推给悬浮窗（跟 `vntext:line` 同一条 `evaluate_js` 链路） | ⏸ 搁置（使用者明确暂不做） |

**P8.11 修掉的两个真机 bug（都不是「上一轮没做完」，而是上一轮真机门没跑才漏出来的）**

| bug | 现象 | 根因 | 修法 |
| --- | --- | --- | --- |
| 画廊「色块不一致」（使用者实机反馈） | 列表布局下右栏与底栏那条**比别处明显更暗**；浅色态尤其刺眼 —— 右下一整块 lum≈60，旁边 242 | 布局层 `#hall::before` 的整屏遮罩把**极光的深蓝黑写死**（`rgba(3,4,9,…)`），而画廊的整屏遮罩只写了 `#hall:not(.hall-list)`（列表布局改用局部 hero 遮罩）→ 列表布局漏用默认色 | `layout.css` 改成 `rgb(var(--scrim-rgb) / …)`：四套主题任何布局都跟自己的深浅走；写了整屏遮罩的皮肤照旧覆盖 |
| 悬浮窗不出现 | `e2e` 第 85 步 `1 个窗口`（期望 ≥2）；日志 `overlay html missing: …\gl\web\overlay.html` | P8.9 删 v1 时只改了主窗入口；且 v2 产物是 ES module，`file://` 下会被拦 | `HTML_PATH` 指到 `gl/web/v2/overlay.html` + `main.build_window()` 注入 `{server.url}/v2/overlay.html?v=…`；`check_packaging.py` 加断言 |

**本轮已关闭的**（原清单 1–7 条 + 第 12 条）：模糊归零、字号放大、画廊饱和度、极光毛玻璃、
参考图两块、删 v1、令牌值域守卫、主 CTA 四套风格化 —— 代码与产物全部落地，离线门全绿；
只剩上面的真机门。逐条做法与验收口径见
[`../frontend-ux-feedback.md`](../frontend-ux-feedback.md) 第四轮 + 本文第 2 节。

**一个反直觉的坑（本轮踩到）**：`git rm -r` 一条命令会把**未跟踪的邻居**一起带走 ——
删 `gl/web/app*` 时 `gl/web/` 整个目录（含未入库的 `gl/web/v2/` 产物）被清掉，
`gl/sources/` 里两个文件也一起没了。产物用 `cd frontend && npm run build` 重建即可
（`vite.config.ts` 的 `outDir` 就是 `gl/web/v2`），但那两个文件得 `git checkout` 回来。
**教训：删 v1 这类操作一次只删一条路径，删完立刻 `git status` 复核。**

## 6. 主题钩子速查（P8.7 之后）

皮肤只允许改线、排印、材质三件事；要动几何就改令牌。写新样式时先看这里有没有现成钩子：

| 界面 | data-slot |
| --- | --- |
| 顶部栏 | `toolbar` / `brand` / `search` / `switch` / `win` |
| 大厅 | `hero` / `hero-label` / `rule` / `title` / `meta` / `desc` / `cover` / `cover-art` / `cover-frame` / `tile` / `card` / `row` / `row-time` / `rail` / `rail-title` / `rail-sub` / `rail-hint` |
| 游戏页 | `stage-top` / `back` / `title` / `meta` / `desc` / `actions` / `play` |
| 书架页 | `nav` / `nav-row` / `nav-label` / `section-title` / `section-sub` / `tile` / `cover-art` / `tile-title` / `tile-meta` / `card` / `bar` |
| 设置页 | `page-head` / `page-title` / `nav` / `nav-row` / `surface` / `section-title` / `note` / `theme-card` / `row` |
| 面板 / 详情页 | `sheet` / `sheet-head` / `thumb` / `thumb-label` |
| 弹窗 / 提示 | `modal` / `modal-title` / `toast` |

## 7. 常用探针（都在 `_sandbox/`，一次性，不入库）

| 脚本 | 干什么 |
| --- | --- |
| `probe_persistent_bg.py` | 常驻背景五步验证（沙盒数据，不碰真实库） |
| `probe_controls.py` | 设置页控件（开关/滑杆/键名/术语表）落盘验证 |
| `verify_demos.py` / `element_flatness.py` | 示例页 DOM 自检 / 扁平度计数 |
| `fix_baseline_keys.py` | 单张基线被污染时，重录指定 key（两次截图一致才写回） |
| `shoot_demos.py` + `shrink_previews.py` | 重渲 `docs/theme-demos/preview/*.jpg` |
| `probe_toolbar_toast.py` | 顶部栏几何（窗口按钮右缘 / 两个图标 / 范围菜单）+ 提示条位置，读 DOM rect，**不抓屏** |
| `probe_printwindow.py` | `PrintWindow` 自绘抓屏的颜色保真度与稳定性对照 |
| `probe_theme_game_state.py` | 游戏页状态在两次运行之间是否一致（比对 DOM rect / 文案） |
| `shoot_layouts.py` | 按「主题 × 布局」出图（`list` / `flat` 不在主题矩阵里，用它补人眼复核） |
