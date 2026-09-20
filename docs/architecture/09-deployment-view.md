# 09 部署视图（deployment-view-writer）

## Summary

部署形态是**免安装单文件 exe + 数据目录**：程序本体是临时解压的 PyInstaller 产物，真相全在数据目录；
外部能力（WebView2、LE、Textractor、解压器、OCR）靠探测 + 降级，不打包、不下载、不修改。

## 部署元素

| 元素 | 运行位置 | 伸缩单位 | 有无状态 | 安全注意 | 可观测性 |
| --- | --- | --- | --- | --- | --- |
| Aurora 主进程 | 用户机（单实例，`Global\AuroraGameLauncher_SingleInstance`） | 1 | 无（状态在数据目录） | 单实例互斥防多开抢库 | 结构化日志 + 诊断包 |
| UI 渲染进程 | WebView2（Chromium，多进程）或 Qt | 内核决定 | 浏览器 profile 在 `data/webview` | 页面只经本地资源服务取资源；不暴露数据目录 | 前端错误进 `window.__auroraErrors`，可回传 |
| 悬浮窗 | 独立无边框置顶窗口 | 1 | 样式在 settings | 默认鼠标穿透；补 `WS_THICKFRAME` 供缩放 | 状态随 `vntext:status` |
| 本地资源服务 | 主进程内的 HTTP 线程 | 1 | 无 | 仅 127.0.0.1、仅 GET/HEAD、拒绝 `/state`、防穿越 | 访问失败写日志 |
| TextractorCLI | 用户自装，子进程（每次会话按位数选 x86/x64） | 1–2 | 无 | 不打包不修改；协议无版本号 | CLI 输出行计数 + 状态事件 |
| Locale Emulator | 用户自装，`LEProc.exe` 拉起的引导进程 | 0–1 | LE 全局配置在用户侧 | 只调用，不下载 | 启动结果 + PE 位数判定 |
| 7-Zip / WinRAR | 用户自装，子进程 | 按需 | 无 | 只解压到目标目录，不删原包 | 解压结果与错误码 |
| Windows OCR | 系统组件（WinRT） | 按需 | 无 | 只处理本机窗口截图 | 语言可用性 + 采样计数 |
| 游戏进程 | 用户机 | 1..n | 游戏自己的存档 | 只读内存扫描（可选、手动触发） | 进程树快照 + 会话记录 |
| 数据目录 | `AURORA_DATA` → 程序目录 `data/`（可写）→ `%LOCALAPPDATA%\aurora-launcher` | 1 | **有状态** | `state/` 不进导出、不对外服务 | 文件大小/写入失败进日志 |
| 打包产物 | 根目录 `Aurora.exe`（PyInstaller 单文件） | 1 | 无 | 不含用户素材与密钥 | 构建日志 |

## 环境假设

| 项 | 假设 | 不满足时 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 x64 | 未定义（不支持） |
| Edge WebView2 运行时 | Win11 自带；Win10 可能缺失 | 回退 Qt 内核（界面效果略降） |
| Python | 打包版无需 Python；源码运行需 3.13 + `requirements.txt` | 源码模式不可用 |
| 外部工具 | 全部可选，用户自装 | 对应能力降级（见 `11`） |
| 数据目录可写 | 优先程序目录，不可写回落 `%LOCALAPPDATA%` | 只读介质下自动回落 |
| 显示与 DPI | 支持高 DPI；窗口尺寸按显示器缩放钳制 | 最小尺寸由后端钳制 |

## 打包与发布

- 入口固定 `main.py`；两个 `.bat`（`启动 Aurora.bat` / `调试启动.bat`）必须 GBK + CRLF，由 `tools/make_bat.py` 生成。
- PyInstaller 参数固定：winrt 动态导入需显式声明；`numpy/pandas/tkinter/pytest` 等排除以减体积。
- **单一清单**：前端资源树与排除项由一份清单描述，`tools/build_exe.py` 与运行时共用；
  继续排除 `web/{userbg,usercovers,usericon}`（用户素材不进发布包）。
- 发布形态：把 exe 与 `docs/`（可选）拷走即可；升级只替换 exe，数据目录不动。
- 迁移与降级：新版本首次启动自动迁移 v1 → v2 并备份；用户可拿备份回退到旧版本继续用。

## 部署风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 杀毒/审计工具拦子进程注入 | 钩子链路不可用 | 明确「不打包不修改 Textractor」，失败时提示改用 OCR 或 LunaTranslator |
| 单文件 exe 首次启动解压慢 | 冷启动变慢（Q1） | 启动打点监控；必要时评估 one-dir 发布 |
| 端口冲突 / 多实例 | 页面互串（历史上 WebView2 固定 42001 的坑） | 取空闲端口 + 单实例互斥（保留现有做法） |
| 数据目录混用 | 不同版本 exe 指向同一数据目录 | schema 版本校验：v2 程序可读 v1 并迁移；v1 程序读 v2 会提示（不静默损坏） |
| 用户素材体积膨胀 | 磁盘占用（截图墙 30+ 张/游戏） | 素材体积治理（`10` H9）+ 手动清理入口 |

## Evidence vs assumptions

- **证据**：单实例互斥名、空闲端口、数据目录回落、winrt 显式声明、`.bat` 编码要求均来自现有实现与 README。
- **假设**：用户机器上外网可达（LLM/资料源）；不假设有管理员权限（调试器路径可能受限 → 降级）。
- **不确定**：exe 体积与 one-file 解压时间没有基线数据 → P0 记录构建产物大小与冷启动耗时作为回归基线。

## Recommended next skill

`scalability-hotspot-detector` → 见 [`10-scalability-hotspots.md`](10-scalability-hotspots.md)。
