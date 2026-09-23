# 13 落地路线（roadmap）

## Summary

8 个阶段，每阶段都能独立发布、独立回滚。原则：**先冻结契约，再搬纯逻辑，再动数据，最后才动边界与前端**；
每一阶段结束都必须让现有真机探针保持通过。

## 阶段总览

| 阶段 | 目标 | 主要交付 | 验收（必须全过） | 回滚方式 |
| --- | --- | --- | --- | --- |
| **P0 基线冻结** ✅ | 让「现状」变成可断言的数字 | 契约快照（105 + 4 方法、14 事件）；去敏库夹具；能力/线程/体积基线；`tests/` + 离线检查与 CI 骨架 | 快照与今日行为一致；`run_all.py` 6/6、`pytest` 7 passed | 仅新增文件，删掉即回滚 |
| **P1 纯逻辑分层** ✅ | 把规则从 IO 里剥出来 | `aurora/domain/*`（文本规则、匹配打分、引擎规则、会话结算）；`gl` 转发 shim | 82 个金样本逐字一致；`pytest` 15 passed；`selftest.py` 10/10、`meta_offline.py`、`vntext_probe.py`、`session_probe.py` 通过 | 删除 `aurora/`，恢复原 import |
| **P2 数据 v2** ✅ | 让数据可迁移、可恢复、写入成本降到常量级 | `state/{settings,library}.json` + `state/sessions.jsonl`；迁移器 + 备份 + `--check`；单写者 + 去抖 | 迁移全等断言；去抖与强杀不损坏；回滚可用；导入/导出兼容且脱敏 | 用备份回到 v1 文件；代码回退版本 |
| **P3 用例服务化 + 桥接 mixins** ✅ | 拆掉 2232 行的 `api.py`，契约零漂移 | P3.1/P3.2 已完成：`ui/bridge/{window,shell,settings}.py`（41 个方法，`api.py` → 1808 行）；P3.3：其余方法 + `app/services` + `TaskRunner`/`EventBus` | 契约 diff = 0；`check_bridge.py` 无缺失；真机启动/翻译/钩子查找抽测通过 | 按 mixin 粒度回退到旧方法实现 |
| **P4 前端 ES 模块化** | 3688 行 IIFE → 模块 + 单一状态层 | `ui/web/app/**`；`core/api.js`、`core/store.js`；打包清单单一来源 | `e2e.py` 90/90；`visual.py` 全过；`__auroraErrors` 为空 | 保留旧 `app.js` 一个版本，按开关回退 |
| **P5 资产服务化** | 资产单一来源，取消 web 目录复制 | `infra/webserver.py`；`/assets/` 映射；删除 `sync_user_assets` | 双内核下封面/背景/图标正常；越权与穿越用例被拒 | 开关回退到「复制到 web 目录」的旧机制 |
| **P6 插件与规则包** | 让社区贡献不需要读核心代码 | `data/plugins/*` + manifest；`data/rules/engines/*.json`；`docs/engines.md` 自动生成 | WillPlus/Artemis 实测码从规则包带出；`vntext_live.py` 真机通过 | 保留内置规则为默认，关掉插件目录加载 |
| **P7 治理收口** ✅ | 让边界与契约长期不腐化 | CI 全量（单元 / 契约 / 迁移 / 守卫 / 打包 dry-run）；诊断包；README 与开发文档同步 | 离线检查全绿；真机矩阵无退化；故意违规能让 CI 变红 | 关闭新检查（不推荐），或回退对应阶段 |

## 每阶段的固定动作

1. **开始前**：跑一次基线（`tools/check_bridge.py` + 本阶段相关探针），把结果留档。
2. **进行中**：只做本阶段范围内的改动；跨阶段需求进待办，不在迁移期顺手"优化"。
3. **结束前**：契约快照 diff、层级守卫、相关探针、文档同步四项检查。
4. **发布**：exe 体积与冷启动耗时与 P0 基线对比；差异超 20% 需在阶段报告里解释。

## 真机 / 联网验收矩阵（每个涉及相应子系统的阶段都要跑）

| 脚本 | 覆盖 | 期望 |
| --- | --- | --- |
| `tools/e2e.py` | 大厅 / 游戏页 / 设置（含插件区与诊断包）/ 分类 / 拖拽 / 缩放 / 布局 / 顶部栏排布 | 96/96（0 skipped） |
| `tools/visual.py` + `visual_summary.py` | 封面与缩略图真实渲染、环形层次 | 判据全过 |
| `tools/selftest.py` | 文件名推断 + 多源匹配 | 10/10 |
| `tools/test_multisource.py` | 多源兜底 | 21/21 |
| `tools/vntext_live.py`（hook / OCR） | 真机取词 + 翻译 | 全部干净 + 有译文 |
| `tools/vntext_probe.py` | 清洗规则 / 协议 / 缓存 / 术语表 | 全部通过 |
| `tools/session_probe.py` | 进程树判定、时长结算、LE argv | 全部通过 |
| `tools/download_probe.py` | 资源站、监听、解压、自动入库 | 全部通过 |
| `tools/locale_probe.py` / `net_probe.py` / `theme_probe.py` | 转区 / 网络 / 主题 | 全部通过 |

## 明确不做（本路线范围外）

- 跨平台、安装器、自动更新通道。
- 账号体系、云同步、社区规则在线分发。
- 服务化 / 多窗口 / 第三方 API 开放。
- 前端构建链（Vite/TS）与运行时新依赖。
- 改写清洗与钩子规则本身（本次只搬位置、加回归，不改行为）。

## 阶段状态

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| P0 基线冻结 | ✅ 已完成（2026-09-20） | [`baseline.md`](baseline.md)：契约快照 + 去敏夹具 + 探针清单 + 架构基线 + `tools/checks/run_all.py`（6/6）+ `.github/workflows/offline-checks.yml` |
| P1 纯逻辑分层 | ✅ 已完成（2026-09-20） | [`p1-domain-migration.md`](p1-domain-migration.md)：82 个金样本 + 转发 shim + 分层守卫激活；`gl/vntext.py` 2145 → 1359 行 |
| P2 数据 v2 | ✅ 已完成（2026-09-20） | [`p2-data-v2.md`](p2-data-v2.md)：state/ 分账 + 迁移器 + 单写者；`pytest` 26 passed；真实库迁移计划 24 游戏 / 123 会话 |
| P3.1 桥接 mixin（窗口 / Shell） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md)：22 个方法搬进 mixin，`api.py` 2232 → 1993 行，契约零漂移 |
| P3.2 设置类方法（settings mixin） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节：19 个方法 / 223 行搬出，契约仍 106 方法 |
| P3.3 游戏库类方法（library mixin） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节：37 个方法 / 491 行搬出，`api.py` → 1292 行，契约仍 106 方法 |
| P3.4 元数据 + vntext/钩子/悬浮窗（56 个方法） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节：`api.py` → 309 行（只剩 14 个方法） |
| P3.5 启动/会话/下载（10 个方法） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md)：`api.py` → 160 行（只剩 4 个方法），7 个 mixin |
| P3.6 第一批 TaskRunner/EventBus + 平台层 winapi | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节；`pytest` 31 passed |
| P3.7 线程收编（17 处）+ 回调改事件 | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 执行记录：裸线程清零、6 个内部事件主题接入、`pytest` 33 passed |
| P3.8-a 设置类服务化（SettingsService） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 执行记录 a：11 个桥接方法变一行转发 |
| P3.9 依赖收口（platform/infra/ui 归位 + 对话框端口） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) P3.9 小节：19 个模块归位，真机矩阵 e2e 90/90 |
| P3.10 「找钩子」重做（签名播种 + 寄存器偏移 + 磁盘镜像扫描） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) P3.10 小节：アマカノ３ 第一个候选即命中 `HS65001#-6C@1B1F70:Amakano3.exe`，界面/服务两级验收通过，`pytest` 46 passed |
| P3.10-b 依赖收口（memmatch / hookfinder → `aurora/platform`） | ✅ 已完成（2026-09-20） | 同上 P3.10-b 小节：`gl` 下留透明别名壳，老探针无需改动，`run_all` 7/7 |
| P3.10-c/d 用户实测修复（找钩子取样 / 设置不保存） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) P3.10-c 与 P3.10-d：真机跑通找钩子；设置改名漏改改回来，新增「桥接转发目标」守卫（`run_all` 8/8） |
| P4.1 前端 ES 模块化第一步（`app.js` → 模块 + `core/api.js`） | ✅ 已完成（2026-09-20） | 页面本来就走本地 http（pywebview 内置服务器），ES 模块直接可用；`e2e` 90/90、`visual` 无 JS 错误；打包清单新增 `app/` 模块树 |
| P4.2 状态收编（`core/store.js` + 实体更新 helper） | ✅ 已完成（2026-09-20） | 同上 P4.2 小节：`app.js` 3889 行、实体更新全部走 store；`run_all` 8/8、`e2e` 90/90 |
| P4.3-a 共享 DOM 层（`core/dom.js`） | ✅ 已完成（2026-09-20） | 同上 P4.3-a 小节：元素表/`$`/`missingIds` 独立成模块，`app.js` 3838 行；`e2e` 90/90 |
| P4.3-b 第一块视图（`views/categories.js`） | ✅ 已完成（2026-09-20） | 同上 P4.3-b 小节：依赖注入 ctx，视图不反向依赖主模块；契约/分层守卫改扫整棵前端模块树；`app.js` 3744 行、`e2e` 90/90 |
| P4.3-c 设置视图（`views/settings.js`） | ✅ 已完成（2026-09-21） | 同上 P4.3-c 小节：ctx 改「箭头延迟取值」避开 `const` 的 TDZ（首次直接传引用 → e2e 3/13）；`app.js` 3719 行、`e2e` 90/90 |
| P4.3-d 大厅自检读出面（`views/hall.js`） | ✅ 已完成（2026-09-21） | 同上 P4.3-d 小节：`__aurora.ring()/layout()` 取数搬进 hall 模块（纯函数传参），返回结构零变化；`app.js` 3695 行、`e2e` 90/90 |
| P4.3-e 环几何进 hall 模块（`RING_GEOMETRY` / `ringGeometryOf`） | ✅ 已完成（2026-09-21） | 同上 P4.3-e 小节：几何常量与纯计算搬走，动画写入方留主模块；`e2e` 90/90、`visual` errors=[] |
| P4.3-f 单张封面变换（`placeRingTile`） | ✅ 已完成（2026-09-21） | 同上 P4.3-f 小节：`visual` 的 ring 判据数值与改前逐字相同；`e2e` 90/90 |
| P4.3-g 环叶子 helper（`ringMod`/`ringSigned`/`clearRingStyles`） | ✅ 已完成（2026-09-21） | 同上 P4.3-g 小节：三处定义改 import、8 处引用不变；`e2e` 90/90、ring 判据数值不变 |
| P4.3-h 环样式应用与键列表（`applyRingSize`/`hallKeysOf`） | ✅ 已完成（2026-09-21） | 同上 P4.3-h 小节：`e2e` 90/90、ring 判据数值不变 |
| P4.3-i 平铺排布（`updateFlatRow`） | ✅ 已完成（2026-09-21） | 同上 P4.3-i 小节：两种布局的排布算法都进 hall 模块；`e2e` 90/90、ring 数值不变 |
| P4.3-j 环本体（`createRing`：帧循环 + 拖拽/键盘） | ✅ 已完成（2026-09-21） | 同上 P4.3-j 小节：`app.js` 3618 → 3345 行；`e2e` 90/90、`visual` ring 判据数值逐项不变 |
| P4.3-k 游戏页渲染面（`views/game.js` + `core/time.js`） | ✅ 已完成（2026-09-21） | 同上 P4.3-k 小节：`app.js` 3345 → 3223 行；`e2e` 90/90、`visual` 判据不变 |
| P4.3-l 详情 / 背景面板（`renderDetail`、`renderBgPanel`+`syncBgZoomUi`） | ✅ 已完成（2026-09-21） | 同上 P4.3-l 小节：`app.js` 3223 → 3120 行；`e2e` 90/90、`visual` 判据不变 |
| P4.3-m 换封面 / 手动匹配面板（含 `sourceName` 归位） | ✅ 已完成（2026-09-21） | 同上 P4.3-m 小节：`app.js` 3120 → 2995 行；中途 `ctx.sourceName` 残留被 e2e 拦下（27/46），修复后 90/90 |
| P4.3-n 资料源 / Steam / 获取游戏（新模块 `views/sources.js`） | ✅ 已完成（2026-09-21） | 同上 P4.3-n 小节：`app.js` 2995 → 2800 行；`e2e` 90/90、`visual` 判据不变 |
| P4.3-o 面板管路（`core/panels.js` + 换封面/资料源面板开关归位） | ✅ 已完成（2026-09-21） | 同上 P4.3-o 小节：`app.js` 2800 → 2774 行；探针确认换封面面板 24 个候选；`e2e` 90/90 |
| P4.3-p 游戏内翻译整块（`views/vntext.js`，含绑定与查找器） | ✅ 已完成（2026-09-21） | 同上 P4.3-p 小节：`app.js` 2774 → 2366 行；`e2e` 90/90（翻译页签/钩子/术语/停止全过）、`visual` 判据不变 |
| P4.3-q 筛选/排序/作用域（`core/query.js`）+ 工具条（`views/toolbar.js`） | ✅ 已完成（2026-09-21） | 同上 P4.3-q 小节：`app.js` 2366 → 2233 行；中途漏 import `inScope` 被 e2e 拦下，补齐后 `e2e` 90/90（0 skipped） |
| P4.3-r 推送事件分发（`core/events.js`，14 个主题） | ✅ 已完成（2026-09-21） | 同上 P4.3-r 小节：`app.js` 2233 → 2121 行；探针直接推 `games:imported` 验证；`e2e` 90/90（0 skipped） |
| P4.3-s 窗口外壳（`core/window.js`）与背景层（`views/background.js`） | ✅ 已完成（2026-09-21） | 同上 P4.3-s 小节：`app.js` 2121 → 1862 行；窗口/背景两组 e2e 判据全过、`visual` 判据不变 |
| P4.3-t 设置页整块收口（`views/settings.js`：主题/网络/转区/外观/备份 + 绑定） | ✅ 已完成（2026-09-21） | 同上 P4.3-t 小节：`app.js` 1862 → 1571 行；设置页那组 e2e 判据全过、`visual` 判据不变 |
| P4.3-u 游戏动作（`core/actions.js`）+ 匹配/转区面板（`views/game.js`） | ✅ 已完成（2026-09-21） | 同上 P4.3-u 小节：`app.js` 1571 → 1355 行；中途漏 import `call` 被 e2e+探针抓下，修复后 `e2e` 90/90（0 skipped） |
| P4.3-v 分类工作区整块收口（`views/categories.js`：渲染 + 绑定 + `moveShelf` 补实现） | ✅ 已完成（2026-09-21） | 同上 P4.3-v 小节：`app.js` 1355 → 1093 行；契约调用点 96 → 97、`update_contract.py` 改扫模块树；`e2e` 90/90（0 skipped） |
| P4.3-w 事件绑定交还视图（game / sources / toolbar 各加 `bind()`） | ✅ 已完成（2026-09-21） | 同上 P4.3-w 小节：`app.js` 1093 → 746 行；探针抓到 `closePanel` 漏 import，补上后 `e2e` 90/90（0 skipped） |
| P4.3-x 全局外壳（`core/shell.js`）+ 打包清单守卫（`check_packaging.py`） | ✅ 已完成（2026-09-21） | 同上 P4.3-x 小节：`app.js` 746 → 692 行；`run_all` 9/9（新增第 9 项检查）；`e2e` 90/90（0 skipped） |
| **P4 前端 ES 模块化** | ✅ 已完成（2026-09-21） | `app.js` 3688 → 692 行（只剩工厂装配 + `boot()`）；16 个模块（`core/` 10 + `views/` 8）各司其职；打包清单单一来源且有守卫；`e2e` 90/90（0 skipped）、`visual` errors=[] 且 ring 判据自 P4.3-d 起逐项不变 |
| P5 资产服务化（`infra/webserver.py` + `/assets/` 映射，取消素材复制） | ✅ 已完成（2026-09-21） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) P5 小节：`sync_user_assets` 与三个副本目录删除；离线探针 15/15（首页/模块树/素材可读、4 类穿越与未挂载目录被拒、POST 405、老 URL 投影改写）；真机探针确认素材由 `http://127.0.0.1:<port>/assets/…` 200 返回；`e2e` 90/90（0 skipped）、`visual` 判据不变 |
| P6.1 引擎规则包（`infra/rules.py` + `aurora/rules/engines/*.json` + 文档生成） | ✅ 已完成（2026-09-21） | 同上 P6.1 小节：导出脚本 `tools/export_engine_rules.py`（与 domain 常量逐字一致）；用户规则 `data/rules/engines/*.json` 同指纹覆盖并记日志；`run_all` 9 → 10 项（新增 `check_engine_rules`，改一个偏移即变红）；`pytest` 58 passed、`e2e` 90/90（0 skipped） |
| P6.2 插件加载器（`infra/plugins.py` + `app/services/plugins.py` + 桥接查询） | ✅ 已完成（2026-09-21） | 同上 P6.2 小节：manifest 门禁（api_version/kind/id/字段类型）、`importlib` 加载不改 `sys.path`、逐插件状态与失败隔离、连续 3 次失败自动禁用；`pytest` 75 passed（新增 17 个插件用例）、`run_all` 10/10、`e2e` 90/90（0 skipped）；贡献者文档 [`docs/plugins.md`](../plugins.md) |
| P6.3 插件接入资料源（`gl/sources/plugin_source.py` + `SourceManager` 集成） | ✅ 已完成（2026-09-21） | 同上 P6.3 小节：插件源参与 `sources()` / `describe()`，`search` 返回 dict 自动归一成 `Candidate`、`fetch` → `Metadata`；调用走 `CallGuard`（三连失败自动禁用）；`pytest` 76 passed、`run_all` 10/10、`e2e` 90/90（0 skipped） |
| P6.4 翻译引擎插件接入 + 设置页「插件」区（状态 / 权限 / 来源 / 重新扫描） | ✅ 已完成（2026-09-21） | 同上 P6.4 小节：`aurora/app/services/translators.py`（适配器 + 注册表）、`plugin:<id>` 走简介与逐句两条链路、设置页第 8 个页签「插件」；契约 [`contracts/plugin-api-v1.md`](contracts/plugin-api-v1.md)、ADR-0009「加载失败 / 版本不兼容 / 自动禁用必须有界面呈现」已满足；`pytest` 82 passed、`run_all` 10/10、`e2e` 94/94（0 skipped） |
| **P7 治理收口**（CI 全量 / 诊断包 / 文档同步） | ✅ 已完成（2026-09-21） | 交付记录 [`p7-governance.md`](p7-governance.md)：CI 增加打包 dry-run、迁移专项与诊断包三步；`tools/collect_diagnostics.py` + 设置页「导出诊断包…」；README 与架构文档同步；**故意违规两次都让 run_all 变红**（留档 `_sandbox/p7-violation-*.log`）；`pytest` 87 passed、`run_all` 10/10、`e2e` 95/95、`visual` 判据不变 |
| P0–P7 固定动作回填 | ✅ 已完成（2026-09-21） | 每阶段的历史记录、证据与回滚说明见对应交付记录（`p1-` / `p2-` / `p3-bridge-mixins` / `p7-governance`）与 `tools/checks/baseline.json` 的 `history` 字段 |
| **P8 前端 v2**（Vue 3 + Element Plus + 四套主题） | ✅ 已完成（2026-09-22） | 交付记录 [`p8-frontend-v2.md`](p8-frontend-v2.md)、决策 [`../adr/ADR-0013`](../adr/ADR-0013-frontend-build-chain-and-themes.md)：`frontend/` 构建产物入库 + 指纹守卫；布局一套、风格四套（aurora / gallery / screening / shelf）× 深/浅；Element Plus 按需引入（产物 1561 → 430 KB）；主题矩阵截图基线 25 张（`tools/baselines/theme-baseline.json`）；`e2e` 95/95、`visual` ring 判据不变 + 主题 25/25、`run_all` 14/14、`pytest` 127 passed | 
| P8.1 / P8.2 设置页收尾 | ✅ 已完成（2026-09-22） | 同记录：设置页 7 个开关 / 3 个滑杆 / 19 个按钮 / 8 个文本框换 `el-switch` / `el-slider` / `el-button` / `el-input`（视觉仍由 layout.css 决定，组件库提供行为层）；修掉迁移漏掉的四个设置键（`vntext_context_lines` / `vntext_auto_start` / `font` / `opacity`）与术语表列表形状；离线守卫 `check_settings_keys.py` 盯键名、枚举与滑杆值域；产物 485 KB；`e2e` 95/95、主题矩阵 25/25（偏差 0）、`run_all` 14/14、`pytest` 全绿、`Aurora.exe` 已重建 | 
| P8.5 / P8.6 体验反馈收尾 | ✅ 已完成（2026-09-23） | 同记录：侧列表三条（右栏宽度 / 行网格 / 真鼠标命中 —— 环形视口 `pointer-events: none`）；「导入游戏」不再二选一（删 `#addMenu`，e2e 判据同步改写 + 测试面快照重生成）；顶部栏重排（窗口按钮贴右缘 8px、获取游戏 / 浏览范围做纯图标进顶部栏、菜单按按钮 rect 定位）；提示条下移；区分度判红（20.4 / 目标 ≥ 20）；`contrast.py` 加遮挡检测与自绘抓屏，`_common.print_window` 供真机工具复用；`e2e` **96/96**、主题矩阵 **25/25（偏差 0）**、`contrast` **32/32**、`run_all` 14/14、`pytest` 全绿 | 
| P8.7 主题语言铺满全界面 | ✅ 已完成（2026-09-23） | 同记录：圆角收进令牌（契约新增 `--r-xs` / `--r-xl` / `--r-pill`，四套主题各一档：极光 8→26 圆角、收藏架 2–5、放映厅 2–5 方正、画廊 1px 直角），共享布局层的 90 多处写死圆角全部改令牌；投影交给 `--fx-panel-shadow` / `--fx-cover-shadow`；结构钩子补到书架页 / 设置页 / 详情与面板 / 弹窗 / 顶部栏；皮肤只写线、排印、材质；主题契约新增「共享层圆角必须走令牌」守卫（故意违规实测变红）；`e2e` **96/96**、主题矩阵 **25/25（偏差 0）**、区分度 **20.2**、`contrast` **32/32**、`run_all` 14/14、`pytest` 全绿 | 
| P8.8 主题二轮 | ✅ 已落地（2026-09-23 晚；真机门已补跑，见 P8.12） | 交付记录 [`p8-frontend-v2.md`](p8-frontend-v2.md) 的 P8.8 小节 + [`../frontend-ux-feedback.md`](../frontend-ux-feedback.md) 第四轮：模糊归零 / 大厅与详情页字号放大（h1 27→40、`#gTitle` 34→46、meta·desc 12.5→15）/ 画廊饱和度回补（`grayscale .62→.3` + `saturate`）/ 极光恢复毛玻璃（`--fx-blur: 20px`，其余三套 0，写进守卫）/ 参考图两块（画廊标题压画面、放映厅时间轴）；`run_all` **14/14**、`pytest` **127 passed**、`vitest` **38 passed**、产物级校验通过；真机门已在 P8.12 补齐（主题矩阵 **25/25 偏差 0**、`contrast` **32/32**、`e2e` **96/96**）。下一轮 —— 「开始游戏」按钮四套风格化（已在 P8.10 落地）、收藏架引入 Atelier 语言（P8.11 小样已出）；搁置 —— 悬浮窗跟主题 |
| P8.9 删 v1 | ✅ 已完成（2026-09-23 晚） | 决策 [`../adr/ADR-0014`](../adr/ADR-0014-drop-v1-frontend.md)：删 `gl/web/index.html`·`overlay.html`·`app.css`·`app.js`·`app/**`（22 个文件），入口固定 `/v2/index.html`，打包清单只剩 `v2/`；守卫扫描面从 `gl/web/**` 换成 `frontend/src`（`common.frontend_sources()`，主窗 / 悬浮窗分开）；契约快照前端调用点 100 → **103**；架构基线 `superseded_by` 登记 22 条搬家；`run_all` **14/14**、`pytest` **127 passed** |
| P8.8-b 令牌值域守卫 | ✅ 已完成（2026-09-23 晚） | `check_theme_contract.py` 新增第 6 节：`--s-floor` 不透明度 60–95%、`--fx-blur` 非负且**只有极光非零（≥12px）**、`--r-*` 档位单调不减、饱和度 / 压暗 / 阶梯倍率区间；`themes.spec.ts` 加同款镜像用例；**故意违规 4 种实测全部变红**（`_sandbox/verify_theme_value_guard.py`） |
| P8.10 主 CTA 四套风格化 | ✅ 已完成（2026-09-23 晚；真机矩阵已重录并复跑，见 P8.12） | 反馈第 12 条：画廊实色 + 直角 + 1px 内框（原来没覆盖、用的还是蓝色渐变）、放映厅琥珀实色 + 时间码字距 + 按下辉光、收藏架黄铜实色 + 内阴影压印、极光保留渐变但收敛投影；`.btn.primary` 一并收口。产物级校验：三套实色、只有极光是渐变。顺带修掉两处守卫口径不一致（`themes.spec.ts` 数总行数 vs Python 数非空行；`build-info.mjs` 未跳过 Vite 的 `vite.config.ts.timestamp-*.mjs`，会把源文件数从 62 抬到 63）；`run_all` **14/14**、`pytest` **127 passed**、`typecheck` 通过、`vitest` **38 passed** |
| P8.12 真机门补跑 + 两个真机 bug | ✅ 已完成（2026-09-23 深夜） | 真机门全绿：主题矩阵重录 **25/25（偏差 0）**、`contrast` **32/32（tainted 0）**、`e2e` **96/96**。修 ① 画廊列表布局的整屏遮罩回落到极光色（`layout.css` 的 `#hall::before` 改走 `--scrim-rgb`，使用者实机反馈第 13 条）；② 悬浮窗入口还指着 P8.9 已删的 `gl/web/overlay.html`，且 v2 产物是 ES module，改走本地静态服务 + `check_packaging` 加断言。工具侧补 `guard_webview_start()`（`loaded` 超时快失败，不再静默挂死）与 `park_cursor()`（hover 高亮污染逐格比对，实测差 19）；`run_all` **14/14**、`pytest` **127 passed**、`vitest` **38 passed**，`Aurora.exe` 已重建 |
| P8.13 极光玻璃补完 + 画廊顶部遮罩 | ✅ 已完成（2026-09-23 夜，使用者实机反馈第 14、15 条） | ① 极光浅色的白色高光被 `--ramp-s-k: 12` 乘到 alpha 1.0（实心白）→ `backdrop-filter` 形同虚设；改 1.4 且 `--s-floor` 88% → 72%，底栏与 `.btn.glass-btn` 补上模糊（实测「开/关模糊」的像素差：设置页 0.03 → 3.75、游戏页 0.04 → 2.74）；② 画廊整屏冷灰罩原来只覆盖 `#hall:not(.hall-list)`、局部遮罩从 y=84 才开始 → 顶部 84px 没人盖，均改到全布局 / 往上长到窗口顶（逐行剖面在 y=84 不再跳变）。门：主题矩阵重录 **25/25 偏差 0**、`contrast` **32/32（tainted 0）**、`e2e` **96/96**、`run_all` 14/14、`pytest` 127 passed、`vitest` 38 passed，`Aurora.exe` 已重建 |
| P8.14 主页交互与浅色画廊 | ✅ 已完成（2026-09-23 夜，反馈第 16–19 条） | ① 侧栏长名字压时长（`.row-title` 是行内盒，`overflow/text-overflow` 对它无效）→ 名字块级、两行换行、长西文 `overflow-wrap: anywhere`；② 浅色画廊过亮（局部遮罩 94% 白 + 整屏白罩 + 纯白面板）→ 实测整屏 **215.8 → 207.1**（另三套 200.3–204.6，目标 ±5），`contrast` 32/32 未退；③ 删「双击封面启动」（侧栏 `@dblclick` + 环形 `dblclick` + 提示条），`e2e` 第 3.6 步改写成「主页启动按钮直接启动」，前端表面快照 97 → 98 id；④ 大图 + 侧列表在简介下方加 `#btnHallPlay`（`.btn.play`，四套主 CTA 语言自动生效）。门：主题矩阵重录 **25/25 偏差 0**（区分度 20.2）、`contrast` **32/32**、`e2e` **96/96**、`run_all` 14/14、`pytest` 127 passed、`vitest` 38 passed，`Aurora.exe` 已重建 | 本轮 |
| P8.15 右键菜单 + 删悬停切换（反馈第 19-b 条） | ✅ 已完成（2026-09-23 深夜） | ① `#hallMenu`（`.menu glass`，fixed 跟点击点、贴边夹回）四种布局一套：启动 / 加入收藏（已收藏显示「取消收藏」）/ 详情 / 移除游戏（modal 确认 + `remove_game`，不删磁盘文件）；收起时机：点空白 / Esc / 滚轮 / 切布局；② **删掉环形与横滑的「悬停 320ms 即切换」**（`ring.ts` 的 mousemove 定时器整段下掉），滑动只留滚轮 / ← → / 拖拽；③ `e2e` 新增 5 条判据（**101/101**：右键弹菜单、悬停不再抢焦点、菜单里启动 / 收藏 / 详情），表面快照 98 → 99 id。门：主题矩阵 **25/25 偏差 0**（没重录基线 —— 菜单是隐藏元素，25 张画面一张没动）、`run_all` 14/14、`pytest` 127 passed、`vitest` 38 passed，`Aurora.exe` 已重建 | 本轮 |
| P8.16 按钮风格化（画廊） | ⏳ 已排（2026-09-23 定；**模板已存**） | 使用者给的两份样式存进 `docs/theme-templates/`：一般按钮（浅面 + 底部内阴影键程 + 悬停上浮 / 按下沉）与启动游戏按钮（青色实心 + 3px 实色底边 + 按压收边，标签大写字距），另附 `preview.html` / `preview.png` 三态预览（headless Chromium 渲染）。落地前要拍四件事：圆角与投影（画廊现在是 1px 直角 + 无投影）、青色与画廊蓝的取舍、`Istok Web` 没装、启动按钮写死 120px 与 hover 文字滑出。改完要重录主题矩阵 + 跑 e2e | 待排 |
| P9 下一轮：Atelier 第五套主题 | ⏳ 已排（2026-09-23 拍板；右键菜单已在 P8.15 提前做完） | **Atelier 作为第 5 套主题**（`core/theme.ts` 的 `THEMES`、`visual.py` 的 `THEME_MATRIX` 25→30、主题契约、`themes.spec.ts`、tokens/skin 两份文件、示例页预览图）；判据是重录矩阵后 Atelier 与收藏架的色差要够（新基线 gallery–shelf 16.1，目标 20）。小样在 `docs/theme-demos/atelier/` | 下轮 |
| P8.15 五套示例页的启动键 | ✅ 已完成（2026-09-23 夜） | 「给主题 demo 设计风格化按钮，必须有一套区分度高的启动键」：读参考项目 gal-launcher 的 `src/themes/*.css` 取设计思路（**不抄实现**）—— 它把「启动」当仪式核心（Arcade 的 START 是全屏唯一可下压 + 呼吸灯的键、Atelier 的 play-stamp 是唯一正圆印章），用「形状 / 颜色 / 描边 / 光影 / 质感 / 姿态」六重差异把它拎出来。按同思路给五套示例页各做一个启动键，**共用同一份 DOM**：极光=流动光带胶囊 / 画廊=直角双框印章（hover 整块反白 + 左侧竖排编号）/ 放映厅=琥珀 + 灯珠 + 时间码刻度（常驻呼吸辉光）/ 收藏架=黄铜 + 书脊带缝线（hover 向右抽出 3px）/ Atelier=正圆印章（歪 7° → hover 回正放大）。验收用 **headless Chromium 真渲染**（Playwright 自带的 chromium，不用下载）：五套静止 + 五套 hover 逐张核对，对比图进 `docs/theme-demos/preview/buttons-{launch,hover}.jpg`，全页预览一并重渲（新增 `atelier.jpg`）；结构守卫 `_sandbox/verify_demos_static.py` 加了启动键检查（恰好一个 `button.play` + 三部件 + `:active`），五页全过。另写了 `_sandbox/check_demo_button_contrast.py` 做**离线可读性实测**（headless Chromium + WCAG 相对亮度，取文字左右紧邻处的背景中位色；正文 4.5 / 大字 3.0），**抓到一个真问题**：Atelier 的浅玫红印章上白字只有 2.45–2.73，改成朱砂色阶后升到 4.60–5.34（也更像真印章）。五套终值：极光 6.15 / 画廊 16.41 / 放映厅 7.83 / 收藏架 5.34 / Atelier 5.34 |
| P8.11 Atelier 小样 | 🟡 小样已出（2026-09-23 晚；**区分度已能量，方向待定**） | 反馈第 4 项：`docs/theme-demos/atelier/` 出一张独立静态示例页 —— 浅粉工作台 + 切割垫网格（纯 CSS）+ 奶油纸片 + 和纸胶带（`clip-path` 撕口）+ 楷体排印 + 玫红扁平主按钮；**没有动应用里的收藏架**（方向未定，先改就等于提前选了「改造」那条路）。入口页加 `Candidate` 卡、README 补小节与对照行；静态一致性由 `_sandbox/verify_demos_static.py` 校验（5 个页面全过）。**新基线实测 gallery–shelf = 16.1**（旧 14.6，目标 20）→ 数字上「不够」，但反馈第 20 条已拍板「做」第 5 套，排到下一轮：落地要注册 `core/theme.ts` 的 `THEMES`、`visual.py` 的 `THEME_MATRIX`、`check_theme_contract.py`、`themes.spec.ts`（矩阵 25 → 30 张） |
| P8.3 体验反馈第 1、3 条 | ✅ 已完成（2026-09-22） | 记录 [`frontend-ux-feedback.md`](../frontend-ux-feedback.md)：强调色胶囊文字换行/溢出（`.set-row span` → `> span` 一处根治）；深色态亮壁纸不可读（新增 `--s-floor` 给面板垫底 + 修掉 `#bg-scrim` 的非法 `rgba(var(--scrim-rgb), α)` 语法——这层 scrim 此前从未生效 + 游戏页信息列保底 scrim）；设置页说明文字 1.04–3.31 → 8.10–13.01、游戏页简介 1.04–1.76 → 11.59–16.83；新增真机自检 `tools/contrast.py`（32 个采样点，正文 ≥4.5 / 大字 ≥3.0） |
| P8.4 主题区分度 | ⏳ 待排期（已有设计样例） | 同文档第 2 条：深色四套两两平均色差 6.8/255（深浅对照 213.7）。已做四套**示例主页** [`theme-demos/`](../theme-demos/index.html)（同一内容四种设计语言，静态 HTML + 素材出处），落地要放宽 skin 预算、加结构性钩子，并给主题加「区分度下限」守卫 |

## Evidence vs assumptions

- **证据**：阶段划分严格对齐 `06` 的越界清单与 `05` 的守卫规则；验收项全部是仓库里已有的脚本或本次新增的离线检查。
- **假设**：每阶段可以独立发布；维护者能接受「迁移期不接新功能」的节奏。
- **不确定**：P4/P5 的工作量最大且都涉及界面与资源路径，实际排期要在 P3 结束后回填（届时已有契约与测试网）。

## Recommended next skill

`adr-writer` → 12 条决策见 [`../adr/README.md`](../adr/README.md)。
