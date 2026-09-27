# Aurora × Gal Launcher 对比报告

> **对比对象**
> - **Aurora** —— 本工作区项目 `C:\Users\HuHu1\Desktop\Tasks\v4.1\Aurora`，公开仓库 [Zexuan114514/Aurora](https://github.com/Zexuan114514/Aurora)
> - **Gal Launcher** —— [KamiNeko-pre/gal-launcher](https://github.com/KamiNeko-pre/gal-launcher)（Steam 风格的本地 Galgame / 视觉小说启动器）
>
> **取证方式**：Aurora 侧为本地全量读码（含 `aurora/`、`gl/`、`frontend/`、`docs/`、`tests/`、`tools/`）；Gal Launcher 侧为 GitHub API 实测（仓库元数据、Releases、Issues、完整文件树、语言统计）＋其项目文档与 Release Notes。Gal Launcher 未克隆源码，故其代码级结论来自文件树、测试文件清单与发行说明。

---

## 0. 一句话结论

两个项目**同名不同路，而且已经接上了力**。

- **Gal Launcher**：把本地 galgame 库做成"Steam 一样的漂亮货架"的**产品化收藏／展示型启动器**。Electron + React，6 套主题各带独立布局，已发 6 个版本、累计约 **1,843 次下载**、**77 star**、MIT 许可、Issue/PR/CoC/SECURITY/ROADMAP 一应俱全 —— 是一个**面向公众、可下载、可协作**的开源产品。
- **Aurora**：把启动器当壳、把 **galgame 游戏内实时翻译**当核心的**深度技术工具**。Python + pywebview + Vue，5 套主题，靠 **14 份 ADR + 14 项离线守卫 + 合约快照 + 事故驱动回归**治理 —— 工程密度远高于同类个人项目，但**单机自用、0 star、无 Release、无 License**。

两者**不是替代关系，而是"展示层"与"内容层"的互补**。更有意思的是：Aurora 的仓库里保留着对 **Gal Launcher 0.4.0 三套主题的逐像素测量笔记**，并把它的截图当作排版目标存档；而 Gal Launcher 的用户 issue #1 里恰好提出"**整合内嵌的翻译功能（LunaTranslator）**"—— 那正是 Aurora 已经做出**大半**、而 Gal Launcher 在 `ROADMAP.md` 里**明确写下"不打包 OCR / Hook / 大模型翻译引擎"**的那部分。

> ⚠️ **重要边界（据作者 2026-09-26 澄清）**：Aurora 目前实现的是**置顶悬浮窗形态的逐句翻译**（译文显示在游戏画面之上的独立小窗，默认鼠标穿透），**不是"内嵌翻译"**——即把中文直接渲染进游戏自身的文本框、达到类似原生汉化的效果。后者 Aurora 尚未实现；即便最成熟的开源方案 LunaTranslator 也只对部分游戏做到。本报告中所有"游戏内翻译"均指**悬浮窗形态**。

一句话概括分野：**Gal Launcher 把"看"做到了产品级，Aurora 把"读"做到了技术级。**

---

## 1. 基本盘

| 维度 | Aurora | Gal Launcher |
|---|---|---|
| 公开仓库 | [Zexuan114514/Aurora](https://github.com/Zexuan114514/Aurora)（2026-09-14 创建，2026-09-25 最后推送） | [KamiNeko-pre/gal-launcher](https://github.com/KamiNeko-pre/gal-launcher)（2026-05-14 创建，2026-09-13 最后推送） |
| 许可 | **无 License** ⚠️ | **MIT** ✅ |
| 语言构成（GitHub 统计） | Python **1.27 MB** / CSS 173 KB / Vue 160 KB / TS 91 KB / Batch 3 KB | JavaScript **333 KB** / CSS 242 KB / TS 216 KB / PowerShell 10 KB |
| 版本 | 内部 `app_version = 1.0.0`（`tools/checks/baseline.json`）、前端 package `2.0.0`、阶段号 **P8.21** | **0.4.0**（v0.2.0 → v0.4.0，共 6 个 Release） |
| Star / Fork / Open Issue | **0 / 0 / 0** | **77 / 1 / 5** |
| Release | **无**（仅本机 `Aurora.exe`） | 单文件 EXE + 目录 ZIP，累计 **≈1,843** 次下载（0.4.0 759、0.3.0 1,076） |
| 分发体积 | `Aurora.exe` **25,325,901 B ≈ 24.2 MB**（PyInstaller onefile） | `Gal.Launcher.exe` **88 MB** / ZIP **134 MB**（Electron） |
| 提交数（本地 main） | 151 | —— |
| 定位（作者自述） | 「极简毛玻璃质感的本地游戏启动器：导入 exe 自动匹配 Steam / Bangumi / VNDB，带封面与多张壁纸、游戏时长统计、托盘常驻与简介翻译」 | 「Steam 风格的本地 Galgame / 视觉小说启动器 · Organize, rediscover, and launch your local visual novel library — beautifully」 |
| 目标用户 | 玩**日文原版**、需要翻译的玩家 | **收藏量大**、要好看书架的玩家 |

---

## 2. 技术栈

| | Aurora | Gal Launcher |
|---|---|---|
| 语言/运行时 | Python 3.13（CI 固定；源码宣称 3.9+） | Node.js / Electron 38 |
| 桌面壳 | **pywebview 6.2.1**，优先 **Edge WebView2**，缺失时回退 **Qt** | **Electron 38**（Chromium + Node 双运行时） |
| 前端 | **Vue 3.5 + Element Plus 2.14.6 + Vite 5 + TypeScript 5.6 + vitest** | **React 19 + TypeScript 5.9 + Vite 7 + lucide-react + 纯 CSS 主题层**（README 自述） |
| 前端工程细节 | 前端源码 **63 文件 / 10,733 行**；**无路由**（4 个视图由 4 个响应式开关切换）、**无 Pinia/Vuex**（单个 `reactive()` store + 自研 `onUi/emitUi` 总线）；Element Plus **按需只注册 5 个组件**（产物 1561 KB → **430 KB**，组件库 CSS 431 KB → 18 KB）；`build.target = chrome87`（为 Qt 回退内核）、`assetsDir = "bundle"`（因为 `/assets/` 是用户素材挂载点） | 巨型文件集中：`main.cjs` 121 KB / `useLibrary.ts` 54.5 KB / `main.tsx` 42 KB / `styles.css` 67 KB |
| 国际化 | ❌ **完全没有**：界面文案 100% 硬编码简体中文，无 i18n 框架（`settings.lang` 只是**元数据匹配语言**）。术语表是唯一的"翻译术语 i18n"机制 | ➖ README 中英双语，界面中文 |
| 打包 | **PyInstaller 6.22.2** `--onefile --windowed` → 24 MB 单文件 | **electron-builder 26** → `--win dir`（ZIP 目录版）+ `--win portable`（88 MB 单文件）；`signAndEditExecutable: false`（**无代码签名**） |
| 依赖 | 运行时 **2 类**：`pywebview` + 7 个 `winrt-*` 投影包；**无 requests / numpy / PyQt**，HTTP 走标准库 `urllib` | **运行时依赖 0 个**：12 个包全在 `devDependencies`（Electron 38.8.6 / React / Vite / TS / electron-builder 由打包器与 bundler 吃掉），`package.json` 无 `dependencies` 字段 |
| 依赖治理 | ✅ `check_dependencies.py` 白名单 `{webview, winrt}`，加依赖会让 CI 变红 | 未发现同类机制 |
| 测试运行器 | pytest 8 + vitest 2 | **Node 内置 `node --test`**（不引 jest/vitest），一条 `npm test` 串起 40 个测试文件 |
| 前端产物 | 构建产物入库 `gl/web/v2/`，`build-info.json` 记 sha256 指纹（69 文件），CI 比对源码防漂移 | Vite 构建，随 electron-builder 打包 |
| 体积哲学 | ADR-0003「零新增运行时依赖」 | 接受 Electron 体积，换取 Web 生态开发效率 |

**一句话**：Gal Launcher 选了**开发效率与生态**（Electron/React），Aurora 选了**体积与依赖洁癖**（pywebview/手写 ctypes）。Aurora 的 24 MB vs Gal Launcher 的 88 MB，正面回应了 Gal Launcher issue #1 第七条对"Electron 体积与 6–7 秒启动"的抱怨。

---

## 3. 架构

### 3.1 Aurora —— 单体 + 端口-适配器分层，且有 AST 守卫

```
ui ──▶ app ──▶ domain            domain = 纯逻辑（无 IO / 无 ctypes / 无 webview）
        ▲
infra ──┘   （infra 实现 app.ports，可 import domain）
platform ◀── infra               platform = 手写 ctypes Win32 原语
组合根 ──▶ 全部                   唯一装配点 = gl/api.py 的 Api()
```

| 层 | 目录 | 关键内容 |
|---|---|---|
| 组合根 | `gl/api.py`（196 行） | `class Api(WindowBridgeMixin, ShellBridgeMixin, SettingsBridgeMixin, LibraryBridgeMixin, MetadataBridgeMixin, VnTextBridgeMixin, SessionBridgeMixin)` |
| domain | `aurora/domain/` | `text_rules.py` 634 行（文本清洗/去重/折叠）、`engine_rules.py` 250 行（引擎指纹 + H-code）、`matching.py` 244 行（打分） |
| app | `aurora/app/services/` | library / metadata / launch / hooksearch(573) / vntext / translation / translators / settings / diagnostics / plugins |
| infra | `aurora/infra/` | `vntext.py` **1,485 行**（最大文件）、`linetrans.py`、`downloads.py`、`process.py`、`plugins.py`、`store/`（原子写 + 迁移 + 备份） |
| platform | `aurora/platform/` | `hookfinder.py` **909 行**、`memmatch.py` 476 行、`winapi.py`、`screencap.py`、`tray.py`、`hotkey.py`、`proctree.py`、`ocr.py` |
| ui | `aurora/ui/` | `overlay.py` 388 行 + `bridge/` 8 个 mixin |

**通信只有三条路**，无 IPC、无 WebSocket：
1. 前端 → 后端：pywebview `js_api` 单一对象，方法名**冻结**在 `docs/architecture/contracts/bridge-contract.json`（README 记 151 方法 / 14 事件 / 103 个前端调用点；合约文件的 `events` 数组实测为 14 项）。
2. 后端 → 前端：进程内 `EventBus` → **唯一出口** `_dispatch_event` → `evaluate_js("window.__aurora.emit(...)")`，信封 `{topic, seq, ts, payload}`。
3. 本地静态服务：自建 `ThreadingHTTPServer` 绑 `127.0.0.1:0`，`/` 服务前端、`/assets/<mount>/` 映射 `data/` 用户素材（**不复制文件**），**只允许 GET/HEAD**。

**并发模型**：1 进程 + 1 UI 线程 + 有界线程池（`TaskRunner`，8 worker，daemon 化）+ 具名长驻服务线程（清单被 `baseline.json` 登记，新增匿名线程会被守卫发现）+ 外部子进程（TextractorCLI / LEProc / 7z / 游戏本体）。轮询节奏全部有据：会话 1.5 s、心跳 30 s、OCR 0.9 s、下载目录 5 s。

**兼容层手法**：`gl/*.py` 大多是 8–12 行的**透明模块别名**（`sys.modules[__name__] = aurora.xxx`），使 20+ 个老调用点与 `tools/` 探针零改动完成搬迁 —— 这本身就是一次真实的架构演进工程。

### 3.2 Gal Launcher —— Electron 经典三层，但中枢文件很"胖"

- 结构：`electron/main.cjs` + `electron/preload.cjs` + `src/`（React 渲染层），按域切了 6 个目录（integrations / library / metadata / network / packaging / play-session / search / window）。
- 但体量集中度很高：
  | 文件 | 大小 |
  |---|---|
  | `electron/main.cjs` | **121 KB**（单文件主进程） |
  | `src/useLibrary.ts` | **54.5 KB** |
  | `src/main.tsx` | **42 KB** |
  | `src/styles.css` | 67 KB |
  | `src/themes/*.css`（5 份） | 157.6 KB（monolux 46 / aurora 33 / atelier 32 / editorial 25 / arcade 22） |
- 主题范式：**每套主题一个独立 Layout 组件**（`ArcadeLayout` / `AtelierLayout` / `AuroraLayout` / `CinemaLayout` / `EditorialLayout` / `MonoLuxLayout` + `layoutRegistry.ts`）＋一份大体量主题 CSS。
- 模块粒度做得很细（`cover-eligibility.cjs` 仅 207 B、`icon-path.cjs` 240 B、`community-title-match.cjs` 257 B 也各配一个测试），配合 `preload-contract.test.cjs` 守 IPC 契约。

### 3.3 架构对比要点

| 维度 | Aurora | Gal Launcher |
|---|---|---|
| 分层 | 六边形分层 + **AST 守卫强制**（domain 不许有 IO、ui/app 不许 import infra） | Electron 三层 + 目录按域切分 |
| 契约保护 | **桥接方法名快照**（151 方法 / 109 公开，变更必须显式更新 `bridge-contract.json`）；前端唯一出口 `core/api.ts` 的 `call()` 被守卫强制 | `preload-contract.test.cjs` 守 preload 暴露面 |
| 巨型文件 | 4 处超 600 行目标（vntext 1485 / hookfinder 909 / text_rules 634 / hooksearch 573） | `main.cjs` 121 KB、`useLibrary.ts` 54.5 KB、`main.tsx` 42 KB |
| 主题实现 | **一份 DOM + tokens/skin/buttons 三层 CSS**（ADR-0013「多套皮肤一份标记」） | **一套 DOM + 一个 Layout 组件 + 一份主题 CSS** |
| 主题扩展成本 | 加主题 = 加 3 个 CSS 文件 + 注册 | 加主题 = 加组件 + CSS + 注册（还要跑现有构建/检查） |

两种都合理：Aurora 的范式让"同一份标记"跨主题不漂移，代价是 CSS 层数多；Gal Launcher 的范式让每套主题能改**布局与导航方式**（"主题不再只是换色"是其 0.3.0 的卖点），代价是 6 份布局各自维护。

### 3.4 渲染层 ↔ 主进程：两套完全不同的桥接风格

| | Aurora | Gal Launcher |
|---|---|---|
| 机制 | pywebview `js_api` 单一对象（`window.pywebview.api.*`） | Electron `contextBridge` + `ipcRenderer.invoke`（`window.galLauncher.*`） |
| 调用面 | **151 个方法**（109 公开 + 42 内部），全部挂在一个对象上 | **38 个能力**（37 `invoke` + 1 `send`），按 `domain:action` 命名空间扁平暴露（`library:` / `dialog:` / `tools:` / `window:` / `game:` / `image:` / `shell:` / `perf:`） |
| 推送面 | **一条统一事件信封** `{topic, seq, ts, payload}`，14 个主题，按 `seq` 去重，带背压/合并规则（如 `vntext:line` 100 ms 合并、队列上限 500、丢中间态不丢完成态） | **每个事件一条独立通道**（`library:scanProgress` / `tools:progress` / `window:fullscreenChanged` / `game:sessionEnded`），各自返回一个 unsubscribe 函数 |
| 悬浮窗 | 第二个 pywebview 窗口，独立 4 方法桥 + 自己的 `window.vnUpdate` 入口 | 无第二窗口 |
| 进程隔离 | 无沙箱：插件与宿主**同进程**、以用户权限运行（README 与 ADR-0009 如实披露"只保证插件不崩宿主，不保证插件不干坏事"） | `contextIsolation` + `contextBridge`，渲染层拿不到 Node，能力走白名单 |
| 调用点规模 | 前端约 103 个调用点/112 处字面量 | 38 个能力，全部集中在一个 preload 文件（58 行） |

一句话：**Aurora 用"一条通道 + 冻结信封"换统一治理，Gal Launcher 用"一能力一方法 + 一事件一通道"换隔离与可读性。** 前者靠合约快照防漂移，后者靠 Electron 的进程边界防越权。

---

## 4. 功能矩阵

✅ 有 ｜ ➖ 部分/受限 ｜ ❌ 无 ｜ ⏳ 明确排在待办

| 能力 | Aurora | Gal Launcher |
|---|---|---|
| 导入（exe / bat / cmd / lnk / 拖放 / 文件夹） | ✅（`.exe/.bat/.cmd`，拖文件夹向下 3 层，单次上限 40） | ✅（`.exe/.bat/.cmd/.lnk`，自动设工作目录） |
| Steam 库扫描导入 | ✅（读 `libraryfolders.vdf` + `appmanifest_*.acf`） | ➖（README 未列；有 Steam 作为元数据源） |
| 批量导入总目录 | ➖（下载目录监听 + 自动解压入库） | ✅（0.4.0「批量导入」：收录第一层游戏文件夹，优先唯一含 `chs` 的 EXE） |
| 元数据源 | **Steam 商店 / VNDB / Bangumi**（免 Key）+ 自定义 JSON 源 + 跳转源 + **插件源** | 据 README 数据来源表：**GalgameWiki / VNDB / Bangumi / Steam / DLsite / 2DFan / 其他社区页面 / 本地文件**（代码侧可见 `galgamewiki` / `bangumi` / `dlsite-search` / `2dfan-search` 等模块与测试） |
| 多源补图 | ✅（主源命中后 ≥0.95 的其它源图片汇总去重，可关） | ✅（横版图搜索改进标题匹配 + 多源调度） |
| 手动匹配 / 候选面板 | ✅（候选按匹配度排序，点哪条才应用） | ✅（分档资料确认：高置信自动应用、歧义待确认、低置信不覆盖） |
| 封面 / 横幅 / 背景切换 | ✅（封面 + 多张背景 + 本地图 + 100–300% 缩放平移） | ✅（竖版封面用于书架、横版大图用于启动页，可用本地图片） |
| 游玩时长 / 启动次数 / 会话历史 | ✅（进程树判定 + 30 s 心跳 + 最近 5 次会话） | ✅（0.2.3 重写：WMIC 进程树 + journal + 看门狗 + before-quit 快照） |
| **引导进程先退出的误判处理** | ✅（按镜像路径 + 整棵子树认本体） | ✅（进程树追踪，子进程退出后判定） |
| 分类 / 书架 / 收藏 | ✅（自建分类、状态、开发商筛选、批量归类、收藏） | ✅（自定义分类 + 各主题书架 + 题材筛选 + 首字母索引） |
| 状态徽标（在玩/通关/搁置） | ✅ | ➖（有游玩状态与统计） |
| 转区启动（Locale Emulator） | ✅（**只对接本机已装**，四件套校验 + `LEConfig.xml` 配置 + PE 位数判定 + 兜底不拦人） | ✅（0.4.0：可绑定已有 LE，或**按提示下载校验部署官方版本**） |
| 游戏超分（Magpie） | ❌（明确排在后面） | ✅（0.4.0：轻量/均衡/高清/4K 四档，自动部署 + 启动后自动尝试） |
| **手柄导航** | ⏳（`docs/handover.md` 列为低优先级） | ✅（0.4.0：切换作品/启动/浏览资料/进书架/管理分类/切主题/退出全屏） |
| **沉浸式全屏** | ❌ | ➖（0.4.0 已做沉浸式全屏；issue #4 仍在征集"真正全屏 + 窗口状态恢复"） |
| **存档管理** | ⏳（`docs/handover.md:173` 中优先级待做） | ✅ IPC 层已实现 `game:saveBackups` / `game:createSaveBackup` / `game:restoreSaveBackup`（`electron/preload.cjs:38-40`）；`ROADMAP.md` 仍列"存档目录快捷方式 + 手动备份/恢复"为待办（即已有基础、还在补） |
| 托盘常驻 | ✅（纯 ctypes `Shell_NotifyIconW`，无 pystray） | ➖（README 未列为卖点） |
| 代理（手动/环境变量/系统注册表 + 失败换路） | ✅（实测 5/5 端点，含 1.6 s 级 VNDB） | ✅（自动用系统代理 + 环境代理，改进超时与备用路径） |
| 下载目录监听 / 自动解压 / 自动入库 | ✅（zip 内置，rar/7z 需本机 7-Zip/WinRAR；套娃目录摊平；首次只建基线不回溯） | ❌（不做自动下载） |
| 简介翻译（外语→中文） | ✅（LLM 优先，MyMemory 免费兜底，缓存一年，保留原文可切换） | ✅（保留原文、来源及状态，支持重试） |
| 库导入导出 / 备份迁移 | ✅（导出脱敏 API Key，按 exe 去重合并） | ✅（本地优先，支持导出/恢复） |
| 诊断包 | ✅（脱敏设置 + 日志尾巴 + 插件与资料源状态 → zip） | ❌（有 SECURITY.md / PRIVACY.md 说明） |
| 插件 / 规则包生态 | ✅（资料源插件 + 翻译引擎插件 + 声明式引擎规则包，热扫描、状态可见、连续 3 次失败自动禁用） | ❌ |
| 自定义主题（用户放 CSS 即可） | ❌（5 套内置，未开放加载） | ❌（issue #1 第一条建议开放，至今未做） |
| **游戏内逐句翻译（悬浮窗形态）** | ✅ **核心能力**（见 §5；形态是置顶悬浮窗，**非内嵌**） | ❌（issue #1 第六条明确请求整合 LunaTranslator，仍 open；`ROADMAP.md` 列为 Not Planned） |
| 多语言 UI | ❌（界面文案中文硬编码；`settings.lang` 只控制 Steam 简介语言） | ➖（README 中英双语，界面中文） |

**结论**：Gal Launcher 在"**库管理 + 展示 + 外设/增强**"这条线上更完整（批量导入、手柄、全屏、超分、存档、分类体系、6 主题）；Aurora 在"**抓取管线 + 翻译/取词 + 工程治理 + 扩展点**"这条线上更深（Steam 库扫描、下载自动入库、插件/规则包、诊断包、以及碾压级的游戏内翻译）。两边**真正重叠的只有：元数据匹配、封面背景、时长统计、转区启动、简介翻译** —— 也就是"启动器"这个词的共同下限。

---

## 5. 深水区：游戏内逐句翻译（悬浮窗形态，Aurora 独占，且 Gal Launcher 用户正在要）

Gal Launcher **没有任何游戏内取词/翻译能力**。它的 `electron/metadata/translation.cjs`（2.9 KB）负责的是**元数据文本翻译**，不是逐句台词翻译。而它的 issue #1 第六条写着：

> 六、实时翻译 —— https://github.com/HIllya51/LunaTranslator 有可能合作一下，整合一个内嵌的翻译功能吗

**更关键的是：这不是遗漏，是 Gal Launcher 写进路线图的明确取舍。** 其 `ROADMAP.md` 的「Not Planned」最后一条：

> - Bundling OCR, Hook, or large-model translation engines when external-tool integration is sufficient

同时 `ROADMAP.md` 的「Optional Integrations」里对翻译的规划是：

> - [ ] User-configured launch presets for Locale Emulator and **external translators**

也就是说：**Gal Launcher 选择"把外部翻译器当外挂启动"，Aurora 选择"自己把整条取词/翻译管线做进启动器，再用悬浮窗呈现译文"。** 两条路线都能成立，区别在于**呈现形态的完成度**：Aurora 的悬浮窗已经是"开箱即用的逐句翻译"，而"内嵌"（把中文画进游戏文本框，等效原生汉化）两边都没做到 —— 这构成了两个项目最本质的分野：不是功能多少，而是**产品边界取舍不同**。

Aurora 已经把这条路走通，并且是**自研 + 只读**的路线：

### 5.1 取词链路
| 环节 | 做法 |
|---|---|
| 文本源 | 优先驱动**本机已装的 `TextractorCLI.exe`**（不打包、不搬运 GPL 代码）；没装则用**屏幕 OCR** |
| 位数匹配 | 读游戏 exe 的 PE 头判断 32/64 位，自动挑对应 CLI（32 位 galgame 必须用 x86 那份，否则 attach 不上 → `wrong-bitness`） |
| 协议 | stdin/stdout 管道 + **UTF-16LE**；因为换行是 `0A 00`，**不能用 `readline()`**，改用 `read1(4096)` + 手工找 `b"\n\x00"` |
| 时序坑 | 必须先 `attach` 并等 CLI 打印「管道已连接」（超时 6 s）**才能**下发专用 hook 码；同批写会把 CLI 顶掉、一行文本都收不到 |
| 清洗 | `aurora/domain/text_rules.py` 634 行纯函数：逐字×N 折叠 → 成对双写折叠 → 同句多形态去重（8 s 窗口）→ 折行拼接 → 说话人合并 → 噪声门禁 |
| **缺字补全** | `aurora/platform/memmatch.py`：`OpenProcess` + `ReadProcessMemory` + `VirtualQueryEx` **只读**扫内存，用窗口/LCS/汉字跨度把字形钩子吐出的缺字版配成完整台词（**不注入、不改内存、不需要地址**）；实测全量扫描 44–68 s，故取词链路最多等 2.5 s 先放行缺字版，补全版随后作为**同一句的新版本补发** |
| **钩子查找器** | `aurora/platform/hookfinder.py`（909 行）：`DebugActiveProcess` 调试器 + **x86/x64 硬件断点 DR0–DR3/DR7** + `CONTEXT32/64` + **按绘制函数机器码特征码**定位候选（解决 Artemis/Emote 用 D3D11 自绘、GDI 钩子全空）；判据是「输出就是原文」；`DebugSetProcessKillOnExit(False)` 保证退出不带走游戏 |
| OCR 回退 | `Windows.Media.Ocr`（winrt 投影，按需导入，缺失即降级）；截图 `PrintWindow(PW_RENDERFULLCONTENT)` 优先、判黑屏后回退 `BitBlt`；OCR 前抬升游戏窗口但不抢焦点 |
| 引擎规则包 | 声明式 JSON（指纹 = 文件名 + 字节数 + CRC32），用户 `data/rules/engines/*.json` 同指纹覆盖内置；内置 20 个引擎规格 + 每引擎人话 `hook_hint` |

### 5.2 翻译链路
- **优先级**：`plugin:<id>` 插件引擎 → LLM → 免费兜底（MyMemory）。
- **并发**：2 个 worker + 队列上限 4。注释写明实测依据：LLM 单句 40–60 s，单 worker 时翻页要等上一句；**用队列而不是"新顶旧"**，因为掐断在飞请求会导致"一句有一句没有"。
- **`revise_of` 修订机制**：缺字补全出的完整版译文**原位替换**历史里的残句，不新增一条。
- **上下文与术语**：默认前 4 句上下文 + `data/vntext/glossary.json` 术语表（全局 + 每作品两级），保证人称与专名一致。
- **悬浮窗**：`WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOOLWINDOW` + `HWND_TOPMOST` + `SWP_NOACTIVATE`，默认鼠标穿透，自绘边角缩放，`Ctrl+Alt+T`/`Ctrl+Alt+Y` 切换。

### 5.3 真机验证记录（项目自带存档）
`README.md:470-477` 记录了逐作品的实测结论：DRACU RIOT（TVP/KIRIKIRI 16 次翻页 5/5 干净）、少女之剑（WillPlus，`HQ-4@A22E:AdvHD_crack.exe` 专用码 + `merged=9`）、RIDDLE JOKER（双同名线程交替抢先，原始行审计漏掉 0）、悠刻のファムファタル（Escu:de 折行 + 说话人并句）、秽翼のユースティア（BGI 完整版 + 缺字版合并）、白色相簿2（乱码/菜单/视频窗口标题/文件名四类噪声全挡）。

**这部分是 Aurora 真正的护城河**，也是两个项目之间唯一无法靠"抄设计"补齐的差距 —— 它是靠大量真机踩坑（每条都在代码注释与 README 里留了证据）换来的。

---

## 6. 主题与视觉

| | Aurora | Gal Launcher |
|---|---|---|
| 主题数 | **5 套**：极光玻璃 / 展签式画廊 / 夜间放映厅 / 收藏架 / Atelier 工作台 | **6 套**：Cinema / Editorial / Arcade / Atelier / Lumen Shelf / Aurora |
| 外观组合 | 5 套 × 深/浅 = **10 种外观** + **4 个调色板覆盖层**（极光蓝 / 薄荷青 / 樱花粉 / 琥珀橙，只覆盖 `--a-main`/`--a-2`）；由 `<html data-style data-theme data-palette>` 三个根属性驱动，**切换不重载** | 主题即布局，含全屏与窗口态 |
| 明暗 | 每套都有深色 / 浅色态（+ 跟随系统，读注册表实时跟随，DWM 外框一起切） | —— |
| 组织方式 | `<theme>.tokens.css` + `<theme>.skin.css` + `<theme>.buttons.skin.css` 三层 × 5 = **15 个主题 CSS**；布局层 `layout.css` 只有一份（2137 行） | `<theme>.css`（22–46 KB）× 5 + 6 个 Layout 组件 |
| **主题契约守卫**（Aurora 独有） | 每套主题 × 深/浅必须补齐契约清单**全部令牌**；**皮肤 ≤200 非空行**且每条选择器必须限定在自己的 `[data-style]` 下；`--fx-blur` **只有 aurora 非零（12–40 px），其余四套必须恰好 0**；`--r-*` 六档圆角单调不减；共享层**禁止写死 `border-radius`**。故意违规实测会让 CI 变红 | 无 |
| 量化验收 | ✅ 主题矩阵 **35/35（偏差 0）**、**区分度 23.9**（改造前 8.6，目标 ≥20）、对比度 **40/40**（正文 ≥4.5 / 大字 ≥3.0）、按钮状态 640 项最低 **4.94**、截图基线 254 KB | ➖ 有 `docs/assets/screenshots/*`（6 主题 + 预览），无对比度门槛记录 |
| 启动键语言 | 五套各一个（光带胶囊 / 直角印章 / 琥珀灯珠 / 黄铜书脊 / 正圆红印章） | 「启动」是主题仪式核心（Arcade 的 START 唯一可下压 + 呼吸灯、Atelier 的 play-stamp 唯一正圆印章） |

### 有趣的事实：Aurora 量过 Gal Launcher

`docs/theme-demos/README.md:200-214` 有一整节 **「参考：Gal Launcher 0.4.0 的三套主题」**，是读过 `Gal Launcher.exe` 里的 `app.asar` 后得到的**像素级测量表**：

| 参考 | 字体 | 展示字级 | 圆角 | 扁平度（相邻像素差<6） | 主色 |
|---|---|---|---|---|---|
| editorial | Fraunces 衬线 + Inter Tight + JetBrains Mono | **62 / 46 / 40 px** | 14–28 px | 83% | 纸色 `#f3ead8`、墨 `#1d1410`、锈红 `#b8442a` |
| aurora | Manrope + Instrument Serif + Mono | 24 px 以内 | 药丸 + 14–20 px | 79% | 粉 `#fde7ee`、雾蓝 `#e6f1f9`、墨紫 `#3a2a3c` |
| atelier | Caveat 手写 + Press Start 2P + VT323 | 26 px 以内 | 6 px、圆片 | 70% | 桌面 `#efe3d4`、纸 `#fffaf4`、粉 `#e89cb4` |

并明确写下"对我们有用的三条"：**展示字级要敢放大**（editorial 到 62 px）、**按钮是「细边 + 半透明底」而不是渐变块**、**线用墨色/强调色而不是浅灰**。Aurora 随后把详情页字号放大（`h1` 27→40、`#gTitle` 34→46、meta/desc 12.5→15），并把 `docs/images/详情页-Gal Launcher.png` 存为**排版配比目标图**（`docs/architecture/p8-frontend-v2.md:562`、`docs/handover-p8-frontend-v2.md:135`「读参考项目 gal-launcher 的 `src/themes/*.css` 取设计思路（**不抄实现**）」）。

仓库里为此保留了两组参考图：`docs/theme-demos/reference/`（3 张 gal-launcher 截图）与 `docs/images/ux/ref-theme-{aurora,gallery,screening,shelf}.jpg`（4 张按主题对位的对照图）—— 也就是说，**Aurora 的四套主题在定稿前，是逐套对着 Gal Launcher 的同名主题看过一遍的**（连"aurora"这个名字都撞了）。

> 实拍对照（仓库内现成素材）：Gal Launcher 的 Editorial 详情页是「特集·第 001 号 + 62 px 大字标题 + 首字下沉 + 会社/发售/时长/状态四栏 + `立即阅读 LAUNCH` + 页码 p.001/p.002」的杂志跨页；Aurora 的详情页是「左封面 + 右侧标题/元数据/简介 + 纸纹卡」的常规启动器版式，密度更低、依赖壁纸铺底。
> 参考图：`docs/images/详情页-Gal Launcher.png`、`docs/images/详情页-Aurora.png`、`docs/images/书架页.png`、`docs/images/hall.png`。

---

## 7. 元数据与资料源

| | Aurora | Gal Launcher |
|---|---|---|
| 内置源 | Steam 商店、VNDB、Bangumi（**三个都免 Key**） | 据其 README「数据来源」表与 Release Notes：**GalgameWiki、VNDB、Bangumi、Steam、DLsite、2DFan、其他社区页面、本地文件**；0.2.2 记「封面搜索 7 源增强」 |
| 扩展 | 自定义 JSON 接口源（`{query}` 模板 + `results_path` + 字段映射，支持 `a.b` / `a[0].b` / `a[*].b` / `||` 回退）、跳转搜索源、**插件源**（`search()` / `fetch()`） | 无用户自定义源机制 |
| 打分策略 | 完全一致 > 前缀 > 子串 > 词元重合 > 编辑距离，长度差惩罚；「原声带/DLC/试玩版」降权；**只命中次要关键词时阈值更严**（防 `sandbox` 误配） | 标题匹配 + 候选筛选；**续作及版本差异判断**降低本体/续作混淆；分档置信度 |
| 别名处理 | 每个源都拿**全部已知名称**（中文/日文原名/英文）去打分 | GalgameWiki 中文标题及别名检索，与 VNDB 互补 |
| 合规取舍 | **明确不抓 TouchGal / kungal**：前者 TLS 握不上手、后者 `robots.txt` `Disallow: /api`，因此只做「跳转型源」；也不实现自动下载未授权商业游戏 | `docs/DATA_SOURCES.md` 写明 7 条原则：**优先官方 API 而非网页抓取 / 保守请求频率 / 只缓存用户选择的内容 / 显示每个候选的来源 / 让用户手动选择 / 不提交或再分发下载的图片与缓存 / 源不可靠或被站方反对就禁用**；并有独立法务提示段 |
| 源接入细节 | 三源并行打分，主源命中后其它源 ≥0.95 才补图；缓存 TTL 搜索 7 天 / 详情 30 天；图片探测成功缓存 21 天、失败只缓存 3 小时 | GalgameWiki 被刻意**排在 VNDB 之后、Bangumi 之前**（"防止社区查询拖慢成功的 VNDB 搜索，或让等分候选胜出"）；先取最多 30 个索引标题、再最多请求 3 个详情（2 并发）；只接受 category 含「游戏」的条目；**返回 HTML 当不可信输入，只抽纯文本**；归一化标题缓存 5 分钟 |
| 失败语义 | 语义化错误码（`no-query` / `no-results` / `low-confidence` / `network`），**不硬猜**，写 `metadata_state` + `metadata_note` | `PERFORMANCE.md` 回归门槛："元数据网络失败必须可重试，不能写成永久的零分或『查无条目』" |
| 对外定位 | README 无竞品对比表 | README 有对比表，对手是 **Playnite / Steam / 手动管理**（打"Galgame 资料搜索 + Bangumi 评分 + 多来源图片候选 + 视觉小说专用主题"四点） |

> 值得注意的是：**两边都没有把对方写进自己的对比表**。Gal Launcher 对标的是通用启动器 Playnite 与 Steam；Aurora 干脆不做对比表。真正的差异（游戏内翻译）在双方的公开材料里都还没被摆到台面上。

---

## 8. 工程治理

| 维度 | Aurora | Gal Launcher |
|---|---|---|
| 架构决策记录 | **14 份 ADR**（ADR-0001 模块化单体 → ADR-0014 删除 v1 前端），每条含背景/驱动/考虑过的选项/决定/后果/后续动作 | ROADMAP.md（2.3 KB） |
| 架构文档 | **13 篇架构文档**（分层规则、组件边界、集成边界、运行时视图、部署视图、容量热点、可用性与降级、风险登记、路线图）+ 各阶段交付记录（含 763 行 `p8-frontend-v2.md`、671 行 `p3-bridge-mixins.md`、1346 行 `frontend-ux-feedback.md`，35 条编号反馈 / 12 轮） | docs/ 5 篇（DATA_SOURCES / USER_GUIDE / PERFORMANCE / PRIVACY / RELEASE_CHECKLIST） |
| 文档规模 | `docs/` **111 个文件（约 52 个 markdown，全部简体中文）** | `docs/` 5 篇 + 根级 6 篇（README/ROADMAP/CHANGELOG/CONTRIBUTING/CoC/SECURITY） |
| 契约文件 | 4 份（bridge-contract.json、data-schema-v2.md、events.md、plugin-api-v1.md）+ frontend-surface.json | `preload-contract.test.cjs` |
| 单元测试 | pytest **22 文件 / ~127 用例**；vitest 5 个 spec（环几何/查询/时间/主题契约/元素） | **约 40 个测试文件**（`.test.cjs` / `.test.mjs`，含契约、失败路径、性能脚本） |
| 离线守卫 | ✅ **14 项**：合约快照 / 依赖白名单 / AST 分层 / 架构基线漂移（含具名线程清单 + exe 体积）/ 桥接转发目标 / 引擎规则包 / 去敏夹具 / 工具清单 / 打包清单 / 启动冒烟 / 前端构建指纹 / 主题契约 / 前端测试面 / 设置键名 | 未发现同类守卫 |
| 探针/真机验收 | ✅ **32 个脚本**：`e2e.py` 101/101、`visual.py`、`vntext_live.py`（真机取词+翻译）、`contrast.py` 40/40、`session_probe`、`locale_probe`、`net_probe`、`download_probe`、`theme_probe`… 每个都有存档 `*-report.txt` | `scripts/perf/measure-startup.mjs` + `docs/PERFORMANCE.md`（首屏 **446–535 ms**、进程树峰值工作集 **404–432 MiB**，中位 407 MiB，5 次采样） |
| 性能/回归门槛 | 主题矩阵偏差 0、对比度 40/40、契约 diff=0、分层守卫 | `PERFORMANCE.md` 4 条硬门槛：不得重新引入全库 Base64 图片驻留 / 元数据失败必须可重试 / **首屏不得等待 VNDB、Bangumi、翻译、远程字体或非首屏图片** / 主进程职责拆分必须保持现有 IPC 名称与离线启动行为 |
| CI | 1 workflow / 2 job：Python 3.13（守卫 → 打包 dry-run → pytest → 诊断包）+ Node 22（vue-tsc + vitest） | 2 workflow：`build-windows.yml` + **`release-portable.yml`（`workflow_dispatch` + tag 输入 → `npm run check`（测试+构建）门禁 → portable + ZIP → 上传 draft Release）** —— **发布是自动化的** |
| 回归测试文化 | ✅ **事故驱动**：测试 docstring 直接写清事故来源（"2026-09-21 卡死事故"、白色相簿2 实测、冷启动宽限期） | ✅ 模块级测试覆盖细（连 207 B 的 `cover-eligibility` 都有测试） |
| 社区基建 | ❌ 无 CONTRIBUTING / CoC / SECURITY / Issue 模板 | ✅ **CONTRIBUTING + CODE_OF_CONDUCT + SECURITY + PR 模板 + 3 个 Issue 模板（bug/feature/metadata_source）+ FUNDING** |
| CHANGELOG | ❌（用 `docs/architecture/13-roadmap.md` 的阶段记录代替） | ✅ `CHANGELOG.md`（6 KB）+ 每个 Release 有完整更新说明 |
| 已知缺口 | 无 GUI 自动化测试框架进 CI、无覆盖率阈值、CI 不真打包、仓库卫生一般（`_sandbox/` 有中间产物） | 巨型文件、无依赖/架构守卫 |

**一句话**：**Aurora 是架构治理型选手，Gal Launcher 是社区协作型选手。** 前者守住了"代码长期不腐化"，后者守住了"外人能参与进来"。两者恰好是对方最缺的那一半。

### 8.1 版本号与交付状态（两边都有"最后一公里"问题）

| | Aurora | Gal Launcher |
|---|---|---|
| 版本来源 | **三套号并存**：应用 `VERSION = "1.0.0"`（`aurora/infra/store/paths.py:16`）、前端 `package.json` 自称 `2.0.0`、数据 `SCHEMA_VERSION = 2`；对外只有阶段号 P8.21 | 单一 `0.4.0`，CHANGELOG + Release Notes 一致 |
| 更新日志 | ❌ README **没有 changelog / 版本历史**章节，演进只能从 `docs/architecture/13-roadmap.md` + git log 反推 | ✅ `CHANGELOG.md` + 每个 Release 的完整说明 |
| 产物元数据 | `Aurora.exe` 的 **PE 版本资源全为空**（FileVersion / ProductVersion / ProductName 均空），无法从文件属性判断版本 | 有产品名与版本（electron-builder 注入） |
| 提交状态 | ⚠️ **工作区有未提交的 P8.21 改动**（12 改 / 4 删 / 6 新增，含前端源码与重建后的 `gl/web/v2` 产物）—— 分类页交互收口"已完成代码与构建，待真机复核" | 干净的 Release 流程（`release-portable.yml` 自动发布） |
| 索引文档滞后 | `docs/architecture/README.md` 仍写"97 个 DOM id / 13 条 ADR"（实际 99 / 14）；`13-roadmap.md` 的"明确不做"里仍列着"前端构建链（Vite/TS）"，但 ADR-0013 已经引入它 | `ROADMAP.md` 里 "Custom collections"、"Favorite / pinned games"、"More sorting modes"、"Tag filtering" 等仍是未勾选，但 0.4.0 Release Notes 已宣布"自定义分类与排序"上线 —— **路线图落后于发行说明** |
| 文档语言 | 全部简体中文（含代码注释） | README 中英双语，`docs/*` 与 ROADMAP 为英文，Release Notes 为中文 |

---

## 9. 交叉点：这不是巧合，是一条接力线

| 时间 | 事件 |
|---|---|
| 2026-05-14 | Gal Launcher 仓库创建 |
| 2026-07-09 | Gal Launcher **0.3.0**：主题系统大更新，一次上了 6 套主题（含一套叫 **Aurora** 的主题） |
| 2026-09-07 | 用户 issue #1 提 7 条建议，其中**第三条手柄、第四条全屏、第五条存档管理、第六条实时翻译、第七条体积与启动速度** |
| 2026-09-12/13 | Gal Launcher **0.4.0**：一键转区、一键超分、批量导入、分档资料确认、自定义分类、沉浸式全屏 + 手柄导航、删除本体后保留收藏、GalgameWiki 源 |
| 2026-09-14 | Aurora 公开仓库创建 |
| 2026-09-20 → 09-26 | Aurora 完成 P0→P8.21（基线冻结 → 分层 → 数据 v2 → 用例服务化 → 前端 ES 模块化 → 资产服务化 → 插件与规则包 → 治理收口），并**把 Gal Launcher 的三套主题读码 + 量像素后作为设计参考**写进 `docs/theme-demos/README.md` |

**读法**：Gal Launcher 用 4 个月把"货架"做成了产品并开源；Aurora 用 12 天把"货架 + 翻译车间"做成了工程并留下 ADR。Gal Launcher 的用户要的翻译（第六条），Aurora 做了；Aurora 待办清单里的手柄/超分/存档/分类（`docs/handover.md:173-174`），Gal Launcher 已经发了。

---

## 10. 各自的优势、短板与可借鉴项

### 10.1 Gal Launcher
**优势**
1. **发布与社区成熟**：6 个版本、~1,843 次下载、77 star、MIT、完整社区基建、欢迎认领的 Issue 任务、"合并后按贡献署名"的机制。
2. **展示层做得远更厚**：6 套主题**改布局与导航方式**而不只是换色、沉浸式全屏、手柄导航、批量导入、分类 + 书架 + 题材筛选 + 首字母索引。
3. **游戏增强闭环**：一键转区 + 一键超分（Magpie 四档 + 自动部署）、存档管理 —— 都直接对着玩家痛点。
4. **元数据源更多更"中文向"**：GalgameWiki / 2DFan / DLsite / 2DFan 社区页，配合"续作与版本差异判断"防混淆。
5. **体积/性能问题被自己人点出来了**（issue #1 第七条），说明反馈通道是通的。

**短板 / 可借鉴 Aurora 的地方**
1. **没有游戏内翻译 —— 且这是写进路线图的取舍**（`ROADMAP.md` 的「Not Planned」明确"当外部工具集成已足够时，不打包 OCR / Hook / 大模型翻译引擎"，翻译需求被规划为"配置外部翻译器的启动预设"）。但它的用户 issue #1 第六条要的恰恰是"内嵌"。这里存在一个**用户预期与产品边界的落差**：Aurora 已验证的技术路线可参考（只读内存补全、硬件断点找钩子、LLM 流式 + 术语表 + 修订机制、悬浮窗呈现）；若坚持不自研，至少可以把"外挂翻译器"的一键联动做得比现在更顺。
2. **巨型文件**：`electron/main.cjs` 121 KB、`useLibrary.ts` 54.5 KB、`main.tsx` 42 KB —— 可借鉴 Aurora 的"契约快照 + 分层守卫"把主进程按域拆开。
3. **启动 6–7 s / 88–134 MB**（issue #1 第七条）：Aurora 的 24 MB 单文件是一条已经被验证的替代路径（代价是放弃 Web 生态的便利）。
4. **缺依赖与架构守卫**：加一条 `check_dependencies` 式白名单能让"体积/启动"这类问题不再悄悄回退。

### 10.2 Aurora
**优势**
1. **游戏内逐句翻译是全行业少见的深度**：TextractorCLI 驱动 + 位数匹配 + 自研硬件断点钩子查找器 + **只读**内存缺字补全 + OCR 回退 + LLM 流式 + 术语表 + 修订机制 + 鼠标穿透悬浮窗，且每个引擎的坑都有真机记录。（**边界**：呈现形态是悬浮窗；把译文渲染进游戏自身文本框的"内嵌翻译"尚未实现。）
2. **工程治理强度罕见**：14 ADR + 13 篇架构文档 + 14 项离线守卫 + AST 分层守卫 + 桥接合约快照 + 金样本回归 + 去敏夹具 + 事故驱动单测 + 32 个探针脚本与存档报告；主题系统还有令牌契约、皮肤行数上限、选择器作用域、圆角单调性等量化守卫。
3. **零第三方运行时依赖**：只用标准库 + pywebview + winrt 投影，Win32 原语（托盘/热键/截图/进程树/内存/钩子调试器）全部手写 ctypes；24 MB 单文件、免安装、可放 U 盘。
4. **扩展点设计完整**：资料源插件 + 翻译引擎插件 + 声明式引擎规则包，配 `plugin-api-v1.md` 契约、热扫描、状态可见、连续 3 次失败自动禁用，并**如实披露信任模型**。
5. **数据可靠性**：原子写 + 单写者去抖 + 损坏隔离与备份恢复 + 会话追加即时落盘 + 导出/诊断双重脱敏 + 迁移干跑与回滚。

**短板 / 可借鉴 Gal Launcher 的地方**
1. **没有 License** ⚠️ —— 这是最该先补的一项：无 License 即"保留所有权利"，而 Aurora 的文档明确写了参考了 gal-launcher 的设计与 Textractor/LunaTranslator 的思路。补一份 MIT 或注明"参考不抄实现"的许可，能让借鉴关系站得住。
2. **没有 Release** —— 0 star / 0 download 的根因不是质量，而是没有可下载产物与发布说明。Gal Launcher 的"单文件 EXE + 目录 ZIP + 完整 Release Notes"是现成模板。
2b. **对外可读性**：README 594 行、信息密度极高，但**没有 changelog / 版本历史**，`Aurora.exe` 也**没有 PE 版本信息**；加上"三套版本号并存"（应用 1.0.0 / 前端 2.0.0 / 数据 schema 2），外部读者很难判断"现在到哪一步了"。
3. **社区基建空缺**：无 CONTRIBUTING / CoC / SECURITY / Issue 模板 / CHANGELOG —— 而 Aurora 已有插件生态的设计意图（"社区贡献入口"），缺的正是入口的"门槛说明"。
3b. **无国际化**：界面文案 100% 硬编码简体中文、无 i18n 框架；若面向国际用户，这是纯增量工作量（Aurora 已有 `data-style/-theme/-palette` 这类集中化机制，i18n 可以照同一模式做）。
4. **手柄导航 / 沉浸式全屏 / 存档管理**（`docs/handover.md:173-174, 251`）：Gal Launcher 都做了，Aurora 明确排后。其中**存档管理**与 Aurora 已有的进程树/路径推断能力天然契合，性价比最高。
5. **UI 细节**：`docs/images/书架页.png` 里标题被截断为「主播女⋯」「魔法少⋯」「近月少⋯」；主题皮肤在某些页面仍未贯穿（`docs/frontend-ux-feedback.md` 里已有记录）。
6. **仓库卫生**：`_sandbox/`（139 文件，含 Textractor 源码副本等中间产物）、`.pytest_cache`、`data/diagnostics` 历史产物 —— 建议清理或确认已 gitignore。

---

## 11. 风险与注意事项

1. **安全**：Aurora 的 `data/state/settings.json` 里 **API Key 是明文**（`translate_api_key`）。ADR-0011 已经**如实记录**了这个决定（理由：单机桌面、零新增依赖、Windows 用户目录有 ACL），并规定导出/诊断/日志一律剥离脱敏、单测断言导出 JSON 中该字段为空。但本机文件确实是明文 —— 备份/分享 `data/` 目录前请注意。
2. **外部工具依赖（两者共通）**：Locale Emulator、Textractor、7-Zip/WinRAR、Magpie 都**只对接不打包**。Aurora 对 LE 还会校验四件套、判定 PE 位数（LE 只支持 32 位目标）；Gal Launcher 0.4.0 则提供"按提示下载校验部署官方版本"。二者的取舍不同：Aurora 更保守（没装就照常启动、只在角落提示），Gal Launcher 更省事（代下载）。
3. **合规边界**：Aurora 明确不抓 TouchGal / kungal 并说明原因（TLS / `robots.txt`），也不做未授权商业游戏的自动下载；Gal Launcher 使用 DLsite / 2DFan 等网页源。做元数据聚合时这是最容易踩线的地方。
4. **版本号体系不一致**：Aurora 同时存在 `app_version 1.0.0`（baseline.json）、前端 `2.0.0`、阶段号 `P8.x`、数据 `schema_version 2`。对外发布前建议统一。
5. **跨平台**：Aurora 的架构文档**明确不为跨平台预留抽象层**（Win32 原语写得很深：DWM、Toolhelp32、硬件断点、WinRT OCR），跨平台等于重写；Gal Launcher 的 Electron 理论上可移植（issue #1 第二条建议过），但当前也只发 Windows x64。
6. **代码签名**：Gal Launcher 的 Release Notes 明确说明无签名会触发"未知发布者"提示；Aurora 未发布，未来同样要面对。

---

## 12. 总结对照表

| 一句话 | Aurora | Gal Launcher |
|---|---|---|
| 它是什么 | 「启动器 + galgame 游戏内实时翻译车间」 | 「Steam 风格的本地 galgame 收藏货架」 |
| 技术主线 | Python + pywebview(WebView2) + Vue 3，零第三方运行时依赖 | Electron 38 + React 19 + TS，纯 CSS 主题层 |
| 最硬的资产 | 取词/翻译管线（TextractorCLI + 硬件断点找钩子 + 只读内存补全 + LLM 流式）与工程治理（14 ADR / 14 守卫 / 合约快照） | 产品化与社区（6 主题 / 手柄 / 超分 / 存档 / 批量导入 / 6 个 Release / 77 star / MIT / 完整协作基建） |
| 体积 | 24 MB 单文件 | 88 MB 单文件 / 134 MB ZIP |
| 成熟度 | 内部成熟、外部为零（0 star / 0 Release / 无 License） | 外部成熟、内部有债（巨型文件、无架构守卫、无翻译） |
| 对对方的价值 | 给 Gal Launcher 一条已验证的游戏内翻译路线 + 一套架构治理范式 | 给 Aurora 一份发布/社区/展示层/游戏增强的现成模板 |
| 关系 | **互补 > 竞争**。同一批用户的两个刚需：**"让库好看" vs "让日文能读懂"** | |

> 如果要给一句行动建议：
> **Aurora 该学 Gal Launcher 的"对外"**（补 License → 发首个 Release → 加 CONTRIBUTING/Issue 模板 → 顺手把存档管理、手柄、全屏做掉）；
> **Gal Launcher 该学 Aurora 的"对内"**（拆巨型文件 → 加依赖/分层守卫 → 认真评估 issue #1 第六条的翻译需求，那是它用户明确在要、而 Aurora 已经交付的能力）。
