# 06 组件边界（component-boundary-reviewer）

## Summary

把系统切成 **15 个组件**，每个都写清责任、输入输出、数据归属与依赖方向；同时列出当前代码里
**7 处已经越界**的地方（P3 要逐个修掉）。切分原则只有两条：**谁拥有数据谁负责持久化**、
**谁的规则最靠真机现场谁最独立**。

## 组件表

| 组件 | 责任 | 输入 / 输出 | 拥有数据 | 依赖（经端口） | 现位置 → 目标位置 |
| --- | --- | --- | --- | --- | --- |
| `library` | 游戏记录、分类书架、状态、收藏、增删改查与不变量 | 命令 / PublicGame DTO + 变更事件 | `state/library.json` | `LibraryStore` | `gl/store.py` → `domain/library.py` + `app/services/library.py` |
| `metadata` | 关键词推断、跨源打分、候选采纳、跨源补图、批量重抓 | exe 路径 / `Metadata` + 候选列表 | 采集结果写回 library；HTTP 缓存归 `infra/sources/net` | `MetadataSource[]` | `gl/detect.py` + `gl/sources/*` → `domain/matching.py` + `app/services/metadata.py` + `infra/sources/*` |
| `launch` | 启动（含转区）、进程树判定、会话开始/结束、时长结算、启动恢复 | game_id / 会话结果 + `game:running`、`game:stopped` | `state/sessions.jsonl` + library 聚合字段 | `GameLauncher`、`Clock` | `gl/process.py` + `gl/proctree.py` + `gl/locale.py` → `app/services/launch.py` + `infra/launch/*` |
| `vntext` | 文本源选择、钩子会话生命周期、清洗/门禁/去重/并合、OCR 采样 | 游戏 PID / 干净的原文行 + 状态 | 无自有状态文件（运行期状态机） | `TextSource`（hook / OCR）、`SettingsStore` | `gl/vntext.py` → `domain/text_rules.py` + `app/services/vntext.py` + `infra/textractor/*`、`infra/ocr/*` |
| `hooksearch` | 手动触发的钩子查找：采样线程栈、候选收集、验证池、回显判定 | 目标进程 + 期望文本 / 候选 hook 码 | 结果写入该游戏的 `vntext_hook` | `platform/hookfinder`、`TextSource` | `gl/api.py::_hooksearch_*` + `gl/hookfinder.py` → `app/services/hooksearch.py` + `platform/hookfinder.py` |
| `translate` | 逐句翻译、上下文、术语表、缓存、流式事件、暂停/重试 | 原文行 / `delta`/`done`/`error` 事件 | `data/cache/vntext/*`、`vntext/glossary.json` | `Translator`（LLM / 免费接口） | `gl/linetrans.py` + `gl/translate.py` → `app/services/translate.py` + `infra/translate/*` |
| `overlay` | 悬浮窗生命周期、样式、穿透、位置尺寸 | 会话事件 / 渲染指令 + 4 个桥接方法 | `settings.vntext_overlay` | `WindowPort` | `gl/overlay.py` → `ui/overlay.py` |
| `downloads` | 下载目录监听、压缩包解压、自动入库 | 文件系统事件 / 导入结果 + 状态事件 | `settings.download_*`、下载目录 | `ArchiveExtractor`、`library` | `gl/downloads.py` → `app/services/downloads.py` + `infra/launch/archive.py` |
| `settings` | 设置的读取、校验、去抖写入、变更广播、凭据存储 | key/value / 生效的 settings 快照 | `state/settings.json` | `SettingsStore` | `Library.settings` → `app/services/settings.py` |
| `assets` | 封面 / 背景 / 图标落盘、裁剪、去重、体积治理、URL 映射 | 远程 URL 或本地文件 / `asset://` 路径 | `data/{covers,backgrounds,icons}` | `AssetStore` | `gl/api.py::pick_*/set_*/_purge_*` → `app/services/assets.py` + `infra/assets/*` |
| `capabilities` | WebView2 / LE / Textractor / 解压器 / OCR / 代理 / 磁盘可用性探测 | 无 / 能力快照 + 降级建议 | 运行期缓存 | `CapabilityProbe[]` | 分散在 `main.py`、`gl/vntext.py`、`gl/locale.py`、`gl/downloads.py`、`gl/ocr.py` → `app/services/capabilities.py` |
| `diagnostics` | 结构化日志、环形缓冲、诊断包导出 | 日志事件 / 诊断包文件 | `data/logs/*` | `Clock` | `gl/config.log` → `infra/diagnostics/*` |
| `appshell` | 主窗口、无边框拖拽缩放、主题、托盘、拖放、热键 | 用户操作 / 窗口指令 | 无（读写 settings） | `WindowPort`、`platform/*` | `main.py` + `gl/winapi.py` + `gl/tray.py` + `gl/hotkey.py` → `ui/window.py` + `platform/*` |
| `web-ui` | 大厅 / 游戏页 / 设置 / 分类四个视图与视觉层 | 事件信封 + 桥接调用 / 用户操作 | 浏览器 localStorage（仅界面偏好） | `core/api.js`（唯一桥接入口） | `gl/web/app.js` → `ui/web/app/**` |
| `packaging` | 打包清单（前端资源树、winrt 动态导入、排除项）与构建脚本 | 清单 / 单文件 exe | 无 | 无 | `tools/build_exe.py` → 清单 + 构建脚本共用 |

## 端口（`app/ports.py`）

| 端口 | 方法（示意） | 由谁实现 |
| --- | --- | --- |
| `LibraryStore` | `load()`、`save_snapshot()`、`mutate(fn)`、`append_session()` | `infra/store/json_store.py` |
| `SettingsStore` | `snapshot()`、`patch(dict)`、`subscribe(fn)` | `infra/store/json_store.py` |
| `MetadataSource` | `search(query) -> Candidate[]`、`fetch(candidate) -> Metadata` | `infra/sources/*` |
| `TextSource` | `start(pid)`、`stop()`、`lines()`、`status()` | `infra/textractor/*`、`infra/ocr/*` |
| `Translator` | `translate(text, ctx) -> delta/done`、`cancel()` | `infra/translate/*` |
| `GameLauncher` | `start(game, launcher_hint) -> pid`、`tree_pids()`、`kill()` | `infra/launch/*` |
| `ArchiveExtractor` | `available()`、`extract(archive, target)` | `infra/launch/archive.py` |
| `AssetStore` | `put(kind, source) -> rel_path`、`purge(game_id)`、`url(rel)` | `infra/assets/*` |
| `Ocr` | `status()`、`recognize(image, lang)` | `infra/ocr/*` |
| `Clock` | `now()`、`monotonic()` | `infra/diagnostics/clock.py` |
| `EventBus` | `publish(topic, payload)`、`subscribe(topic, fn)` | `app/events.py`（内存实现） |
| `TaskRunner` | `submit(name, fn, timeout)`、`cancel(name)`、`shutdown(grace)` | `infra/tasks.py` |
| `CapabilityProbe` | `probe() -> Capability[]` | `infra/capabilities/*` |

## 当前越界清单（P3 必须修掉的 7 处）

| # | 位置 | 越界表现 | 目标归属 |
| --- | --- | --- | --- |
| B1 | `gl/api.py::_purge_assets/_purge_covers/_remove_icon_files` | 桥接层直接删文件、决定素材生命周期 | `assets` 组件 |
| B2 | `gl/api.py::_hooksearch_worker` | 一个方法里混合调试器采样、UI 状态、点击翻页、验证池 | `hooksearch` + `platform/hookfinder` + `Clock` |
| B3 | `gl/api.py::_recover_sessions/_beat/_on_game_exit` | 会话记账规则写在桥接层 | `launch` 组件 + `domain/session_rules.py` |
| B4 | `gl/vntext.py`（约 1000 行纯函数段） | 领域规则与子进程/OCR IO 同文件 | `domain/text_rules.py` |
| B5 | `gl/store.py::Library` | 数据模型 + 持久化 + 设置混在一个类，且每次改动全量写盘 | `domain/library.py` + `infra/store` |
| B6 | `gl/sources/net.py` + `gl/netproxy.py` | 代理状态通过全局变量 + 全局 provider 注入 | `infra/sources/net.py` 持有显式配置，`settings` 变更经事件推送 |
| B7 | `gl/config.py` | import 期决定 `DATA_DIR` 并执行目录创建 | 路径解析函数 + 在组合根调用 |

## 变更场景检验

| 场景 | 目标形态下要改的东西 | 不该被碰到的东西 |
| --- | --- | --- |
| 新增一个资料源 | `data/plugins/sources/<id>.py` + manifest | `app/services/metadata.py`、桥接层 |
| 新增一个翻译引擎 | `data/plugins/translators/<id>.py` + manifest + 设置页一项 | `app/services/vntext.py`、清洗规则 |
| 新增一条引擎规则 / 实测 hook 码 | `data/rules/engines/*.json`（或内置规则包） | 任何 Python 文件 |
| 调整文本清洗规则 | `domain/text_rules.py` + 金样本测试 | 桥接、窗口、翻译 IO |
| 换存储格式（如 SQLite） | 新增 `infra/store/sqlite_store.py` + 组合根一行 | 所有 app/domain 代码 |
| 新增一个设置项 | `app/services/settings.py` 的 schema + 桥接 mixin + 前端设置页 | 其它服务 |

## Evidence vs assumptions

- **证据**：组件划分来自当前模块的真实职责（24 个 gl 模块 + `main.py`），越界清单逐条对应现有函数名。
- **假设**：`platform` 与 `infra` 的边界用「句柄/内存/窗口 = platform，协议/持久化/网络 = infra」判定；
  `hookfinder` 的采样线程属 platform，候选判定属 domain。
- **不确定**：`assets` 是否值得独立成组件（当前逻辑散在 api.py 多处）。判断依据：素材生命周期有独立的
  失败模式（磁盘、体积、URL 映射），且 P5 会改动它的访问路径，因此独立。

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 组件过多 | 15 个组件对单人项目偏重 | 每个组件 = 一个目录 + 一个服务类，不引入额外框架 |
| 端口抽象过早 | 为「将来可能换」写接口 | 只对满足「要换实现 / 要离线测 / 要复用」三条之一的对象建端口 |
| 迁移顺序错 | 先拆桥接后拆规则，会两边都改 | 严格按 P1（domain）→ P2（store）→ P3（app+bridge）顺序 |

## Recommended next skill

`integration-boundary-mapper` → 见 [`07-integration-boundaries.md`](07-integration-boundaries.md)。
