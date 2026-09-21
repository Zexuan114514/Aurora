# Aurora 架构设计（模块化单体 + 端口适配）

本目录是 Aurora 游戏启动器的架构设计产物集，按 `Aurora/.codex/skills/software-architecture-skills-main`
（14 个技能 / 10 个模板 / 1 个样例流程）组织：**先给选项与依据，再定权衡，然后落到分层、边界、
运行时、部署、容量、可用性、风险，最后用 ADR 固化成硬约束**。

本轮交付的是**文档集 + 落地路线**，不含代码改动；`13-roadmap.md` 是后续实施的唯一入口。

## 这份文档写给谁

| 读者 | 从这里得到什么 |
| --- | --- |
| 维护者（单人） | 每个子系统该放哪、依赖往哪走、改动怎么回退、哪些是硬约束不能碰 |
| 社区贡献者 | 资料源 / 翻译引擎 / 引擎规则包怎么写，契约怎么算被破坏 |
| 未来的接手者 | README 讲「有什么」，本目录讲「为什么是这样、边界在哪」 |

## 系统上下文

Aurora 是一个 **Windows 单机游戏启动器**：界面由 pywebview 承载（WebView2 优先、Qt 兜底），
Python 进程负责游戏库与元数据、启动与游玩时长记账、以及**游戏内文本钩子 / OCR + LLM 翻译**链路。
所有第三方工具都只对接、不打包、不改动。

| 外部依赖 | 方向 | 说明 |
| --- | --- | --- |
| Steam 商店 / CDN、VNDB Kana、Bangumi v0、用户自定义源 | 出（HTTP） | 元数据与图片，可断网降级 |
| TextractorCLI.exe（用户自装） | 双向（子进程管道，UTF-16LE） | 游戏内文本钩子的主路径 |
| Locale Emulator `LEProc.exe`（用户自装） | 出（子进程） | 转区启动，缺省可用普通启动 |
| 7-Zip / WinRAR UnRAR（用户自装） | 出（子进程） | 下载目录自动解压；zip 用标准库 |
| Windows.Media.Ocr（系统组件） | 出（WinRT） | 钩子不可用时的 OCR 文本源 |
| Windows Shell / DWM / 注册表 | 双向 | 默认浏览器、文件对话框、无边框窗口、系统代理 |
| Edge WebView2 运行时 | 运行环境 | 缺失时回退 Qt 内核 |

## 架构驱动与约束

**驱动（Design drivers）**

- **D1 单人维护 + 社区贡献**：结构必须让「加一个资料源 / 加一条引擎规则 / 换一个翻译引擎」是局部改动，
  而不是在 2000 行文件里加分支。
- **D2 零新增运行时依赖**：只有 pywebview + winrt 投影包 + 标准库 / ctypes，架构靠自研小内核实现。
- **D3 真机现场性**：钩子行为、缺字、乱码、折行、OCR 质量都来自真机实测，规则必须可追溯、可回归。
- **D4 免安装分发**：单文件 exe，拷走即用，用户素材与设置必须跟着数据目录走。
- **D5 长驻与崩溃恢复**：可能常驻托盘数小时，游戏退出与启动器退出顺序任意，时长不能丢。

**约束（Constraints）**

- **C1 Windows-only**：Win32 / DWM / 注册表 / PE 头解析是架构的一部分，不做跨平台抽象。
- **C2 pywebview 只暴露 js_api 的顶层方法**：桥接必须是单一扁平对象、方法名即契约。
- **C3 外部工具不可打包、不可修改**：能力探测 + 优雅降级是唯一正确姿势。
- **C4 两个 `.bat` 必须 GBK + CRLF**：由 `tools/make_bat.py` 生成，任何架构调整都不得破坏。
- **C5 单文件 exe 下 `web/` 是临时解压目录**：用户素材必须走数据目录，不能假设打进包里。

## 现状基线（设计依据）

| 事实 | 证据 | 对架构的含义 |
| --- | --- | --- |
| `gl/api.py` 2072 行、`class Api` 146 个方法（105 公开 / 41 内部） | 本目录 `contracts/bridge-contract.json` | 桥接层必须与用例层分离 —— **P3 已完成**：拆成 7 个桥接 mixin + 7 个用例服务，`gl/api.py` 191 行；快照 151 个方法（109 公开 / 42 内部） |
| 前端调用点 96 处、悬浮窗 4 个方法 | `gl/web/app.js`、`gl/web/overlay.html` | 契约可以冻结并快照化 —— **现状 100 处**，由 `tools/checks/check_contract.py` 逐点比对 |
| `gl/vntext.py` 1944 行混合纯规则 / 引擎表 / 子进程协议 / OCR 循环 | 文件结构 | 纯规则必须下沉到 `domain`，IO 上移到 `infra` |
| `gl/web/app.js` 3688 行、`app.css` 1954 行、`index.html` 845 行 | 文件行数 | 无构建 ES 模块化是收益最大的单点改动 —— **P4 已完成**：`app.js` 692 行 + 18 个模块（`core/` 10 + `views/` 8），打包清单由 `check_packaging.py` 守 |
| `data/library.json` 单文件 297KB / 24 游戏 / 60 字段 / 39 项设置 | 实测统计 | 每次改设置全量重写，必须分账 + 去抖 |
| 10+ 处临时 daemon 线程、构造器回调耦合 | `rg 'Thread('` | 需要显式 TaskRunner + 事件总线 |
| 事件 14 个主题、靠 `evaluate_js` 拼 JSON 字符串 | `gl/api.py` | 需要事件信封与统一分发 |
| 用户素材复制进 `gl/web/{userbg,usercovers,usericon}` | `gl/config.py: sync_user_assets` | 资产要单一来源 —— **P5 已消除**：改由 `aurora/infra/webserver.py` 按 `/assets/` 服务 `data/` 下的原图（[ADR-0005](../adr/ADR-0005-assets-single-source.md)） |
| `tools/build_exe.py` 硬编码 4 个前端文件 | 该脚本 | 打包清单要单一来源 —— **P4.3-x 已守住**：清单仍在脚本顶部一份，`tools/checks/check_packaging.py` 对照 `gl/web` 实际目录，漏登记即失败 |
| 契约仅靠 `tools/check_bridge.py` 正则比对，无 CI | `tools/` | 契约要机器可读 + CI 守卫 |

## 产物索引

| 文件 | 对应技能 | 一句话 |
| --- | --- | --- |
| [`01-architecture-options.md`](01-architecture-options.md) | architecture-option-generator | 4 个可信选项与推荐 |
| [`02-quality-attributes.md`](02-quality-attributes.md) | quality-attribute-scenario-writer | 14 条带度量的质量属性场景 |
| [`03-tradeoff-matrix.md`](03-tradeoff-matrix.md) | tradeoff-analysis-writer | 选项 × 准则的权衡矩阵 |
| [`04-modular-monolith-decision.md`](04-modular-monolith-decision.md) | monolith-vs-modular-monolith-reviewer | 为什么留在单进程模块化单体 |
| [`05-layers-and-rules.md`](05-layers-and-rules.md) | layered-architecture-designer | 分层、依赖方向与守卫规则 |
| [`06-component-boundaries.md`](06-component-boundaries.md) | component-boundary-reviewer | 组件责任、数据归属与端口 |
| [`07-integration-boundaries.md`](07-integration-boundaries.md) | integration-boundary-mapper | 11 处内外集成的契约与风险 |
| [`08-runtime-views.md`](08-runtime-views.md) | runtime-view-writer | 7 条主流程与失败路径 |
| [`09-deployment-view.md`](09-deployment-view.md) | deployment-view-writer | 单 exe、双内核、可选外部工具 |
| [`10-scalability-hotspots.md`](10-scalability-hotspots.md) | scalability-hotspot-detector | 9 个容量热点与阈值 |
| [`11-availability-and-degradation.md`](11-availability-and-degradation.md) | availability-strategy-reviewer | 能力探测、降级矩阵、崩溃恢复 |
| [`12-risk-register.md`](12-risk-register.md) | architecture-risk-assessor | 14 条风险登记与实验 |
| [`13-roadmap.md`](13-roadmap.md) | （技能流程收口） | P0–P7 阶段、验收、回滚 |
| [`baseline.md`](baseline.md) | （P0 基线冻结） | 契约 / 夹具 / 探针清单 / 架构基线 / 离线检查与 CI |
| [`p1-domain-migration.md`](p1-domain-migration.md) | （P1 交付记录） | 纯逻辑下沉 domain：映射表、金样本、验收证据 |
| [`p2-data-v2.md`](p2-data-v2.md) | （P2 交付记录） | 数据分账 / 迁移 / 单写者：布局、迁移规则、验收证据 |
| [`p3-bridge-mixins.md`](p3-bridge-mixins.md) | （P3.1 交付记录） | 桥接层拆 mixin：边界、契约守卫如何跟上、验收证据 |
| [`p7-governance.md`](p7-governance.md) | （P7 交付记录） | CI 全量、诊断包、文档同步、故意违规变红的证据 |
| [`contracts/bridge-contract.json`](contracts/bridge-contract.json) | component-boundary-reviewer | 桥接方法签名快照（151 方法 / 109 公开；含前端调用点标记） |
| [`contracts/events.md`](contracts/events.md) | runtime-view-writer | 事件信封、主题表、兼容规则 |
| [`contracts/plugin-api-v1.md`](contracts/plugin-api-v1.md) | service-decomposition-advisor | 插件与引擎规则包契约 |
| [`contracts/data-schema-v2.md`](contracts/data-schema-v2.md) | integration-boundary-mapper | 数据 v2 schema、迁移与回滚 |
| [`../adr/`](../adr/README.md) | adr-writer | 12 条架构决策记录 |

## 阅读顺序

1. **决策依据**：`01` → `02` → `03`
2. **结构**：`04` → `05` → `06` → `07`
3. **运行时与运维**：`08` → `09` → `10` → `11`
4. **风险与实施**：`12` → `13`
5. **硬约束**：`contracts/*` 与 `docs/adr/*`

## 术语

| 术语 | 含义 |
| --- | --- |
| 端口 / 适配器 | 端口是 `app/ports.py` 里的 Protocol；适配器是 `infra`/`platform` 里的具体实现 |
| 组合根 | `gl/api.py` 的 `Api()`（唯一同时接触 app 与 infra 的地方）：构造 store、适配器、七个用例服务与桥接 mixin，注入 TaskRunner 与 EventBus。设计稿里叫 `bootstrap.py`，落地时留在 `Api.__init__` |
| 桥接 | pywebview 的 `js_api` 对象（前端 `window.pywebview.api`） |
| 事件信封 | `{topic, seq, ts, payload}`，后端 → 前端的唯一推送格式 |
| 规则包 | 内置 `aurora/rules/engines/*.json`（由 domain 常量导出）；用户覆盖放 `data/rules/engines/*.json`，同指纹覆盖内置 |
| 能力探测 | 启动时对 WebView2 / LE / Textractor / 解压器 / OCR / 代理的可用性检查 |
| 契约漂移 | 桥接方法名、事件主题、数据 schema 与本目录快照不一致 |
