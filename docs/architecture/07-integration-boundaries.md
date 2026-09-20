# 07 集成边界（integration-boundary-mapper）

## Summary

Aurora 的复杂度一半在内部结构，一半在 **11 处外部集成**：它们各有自己的失败方式、时序要求和
所有权归属。本文把它们逐条记成契约，并标出哪些是「上游一变我们就疼」的脆弱面。

## 集成清单

| # | 边界 | Producer | Consumer | 契约 | 同步/异步 | 所有权 | 风险 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I1 | Steam 商店 | Valve | `metadata` | `api/storesearch`、`api/appdetails`（含中文简介）；封面走 `cdn.cloudflare.steamstatic.com` | 同步 HTTP（带重试） | 上游 | 中：接口限流/结构变化；图片走系统代理，不受启动器代理控制 |
| I2 | VNDB | vndb.org | `metadata` | `api.vndb.org/kana/vn`（JSON，多语言标题、评分、图片） | 同步 HTTP | 上游 | 低：接口稳定；英文简介需翻译 |
| I3 | Bangumi | bgm.tv | `metadata` | `api.bgm.tv/v0/search/subjects`、`/v0/subjects/{id}` | 同步 HTTP | 上游 | 中：R18 条目只返回名称与封面，靠跨源补全 |
| I4 | 自定义资料源 | 用户 | `metadata` | 两种：`kind=api`（JSON 接口 + 字段映射）、`kind=link`（`search_url` 模板 `{query}`） | 同步 HTTP / 打开浏览器 | 用户 | 中：用户配置非法地址与不可达域名；需拒绝非 http(s) |
| I5 | TextractorCLI | Textractor（用户自装） | `vntext` | stdin/stdout 均 UTF-16LE；命令 `attach -P<pid>`、`detach -P<pid>`、`<hook码> -P<pid>`；输出行 `[handle:pid:addr:ctx:ctx2:线程名:hook码] 正文` | 双向流（子进程） | 上游 + 用户 | **高**：协议无版本号；专用 hook 码必须在 CLI 打印「管道已连接」之后再发，否则一行文本都收不到 |
| I6 | Locale Emulator | LE（用户自装） | `launch` | `LEProc.exe -runas <GUID> <exe> [args]` 或 `-run <exe> [args]`；目录需齐 `LEProc.exe`/`LECommonLibrary.dll`/`LoaderDll.dll`/`LocaleEmulator.dll`；`LEConfig.xml` 提供配置 | 同步启动子进程 | 上游 + 用户 | 中：路径发现靠约定目录；只支持 32 位目标；引导进程先退出，判定靠进程树 |
| I7 | 7-Zip / WinRAR | 用户自装 | `downloads` | `7z x <archive> -o<dir> -y -bso0 -bsp0`；`UnRAR x -y`；`WinRAR x -ibck -o+` | 同步子进程 | 用户 | 低：缺失时提示并保留原包；zip 走标准库 |
| I8 | Windows.Media.Ocr | Windows（系统组件） | `vntext` | WinRT 投影包；`available_recognizer_languages` 返回 `ja`，请求用 `ja-JP`，按主语言匹配 | 同步调用（循环采样） | 系统 | 中：日语组件未装时不可用；窗口被遮挡时 DWM 合成可能缺图层（先抬窗） |
| I9 | Windows Shell / 注册表 | Windows | `appshell`、`metadata` | `startfile`、文件对话框、`CreateMutexW`、系统代理注册表、DWM 圆角/暗色边框 | 同步 | 系统 | 低：行为随 Windows 版本调整 |
| I10 | Win32 进程 / 内存 | 游戏进程 | `vntext`、`hooksearch` | Toolhelp32 快照、`OpenProcess` + `ReadProcessMemory`（**只读**）、调试事件 + 硬件断点（hookfinder） | 同步 + 轮询 | 游戏 | **高**：只读扫描不改内存；调试器路径只在用户手动触发时使用；崩溃不得影响主进程 |
| I11 | 本地静态 / 资源服务 | 本进程 | `web-ui` | HTTP/1.1 仅 GET/HEAD；`/` → 随包前端；`/assets/` → 数据目录；拒绝 `/state/*` 与路径穿越；仅监听 127.0.0.1 | 同步 HTTP（本地） | 本仓库 | 中：新增攻击面，需要越权与穿越用例；双内核行为需实测 |

## 契约要点与所有权

### 元数据源（I1–I4）

- 统一端口：`MetadataSource.search(query) -> Candidate[]`、`fetch(candidate) -> Metadata`；
  跨源打分、排序、补图与「是否自动采纳」的判定属 `domain/matching.py`，不属任何具体源。
- 缓存与重试归 `infra/sources/net.py`：TTL 由各源声明、缓存目录为 `data/cache/steam/<source>/<hash>.json`，
  兜底清理 90 天；**缓存不是真相**，删除后必须能重建。
- 代理是一个横切配置：解析顺序为「手动 → 环境变量 → Windows 系统代理 → 直连」，失败时按设置自动换直连；
  图片由渲染进程加载、走系统代理 —— 这个差异必须在 UI 文案里显式提示（现有行为，保持）。

### TextractorCLI（I5，最脆弱）

- 位数必须匹配：x86 游戏用 x86 CLI，x64 反之（读目标 exe 的 PE 头判定）。
- **时序契约**：`attach` → 等「管道已连接 / hijacking process」→ 才允许下发专用 hook 码；
  同批写入会把 CLI 顶掉（实测）。
- 专用 hook 码格式：`H<模式字母><偏移>@<模块内偏移>:<exe 文件名>`；`Q`=UTF-16、`S`=字节串、`V`=UTF-8。
- 失败语义：CLI 退出/管道 EOF 只结束文本源，主进程必须存活并把状态推给界面（`vntext:status`）。

### Locale Emulator 与外部解压器（I6–I7）

- 一律「探测 → 校验四件套 / 可执行路径 → 使用」，缺失时降级（普通启动 / 保留压缩包 + 提示）。
- 转区只对 32 位目标生效；不满足时提示而**不拦**。

### 渲染与系统（I9–I11）

- 双内核：WebView2 优先、Qt 兜底；两者差异集中在 `ui/window.py`，业务不得感知内核。
- 本地资源服务是所有前端资源与用户素材的唯一入口；`data/state/*` 永不对外暴露。

## 契约风险与缓解

| 风险 | 触发 | 影响 | 缓解 |
| --- | --- | --- | --- |
| Steam 接口变更或限流 | 上游改结构 / 触发风控 | 自动匹配失败 | 多源兜底（VNDB/Bangumi/自定义）；失败只影响单个游戏 |
| CLI 协议静默变化 | 用户升级 Textractor | 文本源不可用 | 解析失败按「无文本」处理并提示；保留 OCR 兜底；协议细节写进测试 fake |
| LE 路径/组件变化 | 用户装的版本不同 | 转区不可用 | 四件套校验 + 手动指定路径 + 普通启动兜底 |
| OCR 语言标签差异 | Windows 版本不同 | OCR 判为不可用 | 按主语言匹配（`ja-JP` → `ja`）+ 一键跳转语言设置 |
| 本地服务越权 | 页面被注入或误访问 | 数据泄露 | 仅 127.0.0.1、仅 GET/HEAD、路径规范化、拒绝 `/state`、CI 断言 |
| 只读内存扫描被误判为作弊 | 目标游戏带反调试 | 游戏退出 | 只读 + 用户手动触发；hookfinder 单独开关；文档明确不改内存 |

## Evidence vs assumptions

- **证据**：I5/I6/I7/I8 的契约细节全部来自当前代码与 README 的真机结论（含「先 attach 后发码」这类踩坑记录）。
- **假设**：上游接口保持向后兼容；用户不会把 Aurora 的数据目录或本地端口暴露到公网。
- **不确定**：本地资源服务在 Qt 内核下的行为未实测 → P5 的验收要求双内核都过（`13-roadmap`）。

## Recommended next skill

`runtime-view-writer` → 见 [`08-runtime-views.md`](08-runtime-views.md)。
