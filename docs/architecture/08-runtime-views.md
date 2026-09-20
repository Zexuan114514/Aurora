# 08 运行时视图（runtime-view-writer）

## Summary

运行时形态是「**一个进程 + 一个 UI 线程 + 一组有界后台任务 + 若干外部子进程**」。本文记录 7 条主流程的
参与者、同步/异步边界与失败路径，并把当前 18 个具名线程映射到目标 `TaskRunner` 任务，作为 P3 的搬迁清单。

## 运行时元素

| 元素 | 说明 |
| --- | --- |
| UI 线程 | pywebview 事件循环：处理桥接调用、窗口操作、`evaluate_js` 推送 |
| TaskRunner 任务 | 命名、有界、可取消的业务任务（元数据、翻译、会话监控、OCR…） |
| 本地资源服务 | 本进程内 HTTP 线程：静态前端 + `/assets/` |
| 外部子进程 | TextractorCLI（每个文本会话 1–2 个）、LEProc、7z/WinRAR、游戏本体 |
| 数据目录 | `state/`（真相）、`cache/`（可重建）、`assets/`（用户素材）、`logs/` |

## 主流程

### F1 冷启动

- **主流程**：`main.py` → 单实例互斥 → 解析数据目录 → 迁移检查（v1 → v2）→ 能力探测 → `bootstrap` 装配 → 启动本地资源服务 → 创建主窗口（WebView2 优先，失败换 Qt）→ 绑定拖放/托盘/关闭行为 → 前端 `main.js` 启动 → `bootstrap()` 拉全量快照 → 渲染大厅。
- **同步**：路径解析、迁移、能力探测、窗口创建。
- **异步**：缓存清理、素材索引重建、会话对账（`_recover_sessions` 的等价逻辑）。
- **失败点**：数据目录不可写（回落 `%LOCALAPPDATA%`）；库文件损坏（用备份恢复）；WebView2 缺失（换 Qt）；端口占用（取空闲端口）。
- **恢复**：任何一步失败都要给出可理解的提示，且**不得阻塞界面**；库损坏时保留原文件并另存备份。

### F2 导入游戏

- **主流程**：拖放 / 文件选择 / Steam 扫描 / 下载目录监听 → 展开路径与去重（按 exe 路径）→ 建记录并落盘 → 立即渲染占位封面 → 异步元数据匹配。
- **同步**：路径校验、去重、落盘（去抖前必须先在内存生效）。
- **异步**：关键词推断 → 多源搜索 → 打分 → 自动采纳或列候选 → 图片落盘 → 简介翻译。
- **失败点**：路径不可达；文件名信息太少（`no-query`）；全部源无结果（`no-results`）；置信度不足（`low-confidence`）；网络失败（`network`）。
- **恢复**：失败只写 `metadata_state` + `metadata_note` 并推事件，用户可手动匹配或批量重抓；图片失败不阻塞入库。

### F3 元数据与图片流水线

- **主流程**：`MetadataSource[]` 依次搜索 → 跨源打分 → 采纳详情 → 跨源补图去重 → 图片下载到 `assets/` → 事件推送 → 前端切换封面/背景。
- **同步**：打分与采纳判定（纯逻辑）。
- **异步**：HTTP 抓取、图片下载、批量重抓（进度事件 `batch:progress` / `batch:done`）。
- **失败点**：单源超时/限流；代理路线不可用（自动换直连）；图片 URL 失效（保留占位）。
- **恢复**：单源失败不牵连其它源；批量任务可中断，已完成的部分保留。

### F4 启动与结束游戏（含转区）

- **主流程**：`launch` → 校验 exe → 组装命令（`LEProc.exe -runas/-run` 或直接启动，`.bat/.cmd` 走 cmd.exe）→ 记录 baseline 进程快照 → 启动 → 进程树轮询（1.5s）判定「本体是否在跑」→ 心跳 30s → 自然退出或手动结束 → 结算时长 → 追加会话记录 + 更新聚合字段 → 事件 `game:running` / `game:stopped`。
- **同步**：命令组装、启动调用。
- **异步**：进程树监控、心跳、结算落盘。
- **失败点**：exe 丢失（红色徽标 + `missing-exe`）；LE 缺失或目标非 32 位（普通启动 + 提示）；引导进程先退出（用进程树而非 Popen 存活判断）。
- **恢复**：启动器先退出时用 `play_started_at`/`play_heartbeat` 对账；游戏仍在跑则重新接管。

### F5 游戏内翻译（钩子路径）

- **主流程**：开启翻译 → 能力探测（CLI 位数与目标 PE 匹配）→ 启动 CLI → `attach -P<pid>` → 等「管道已连接」→ 下发专用 hook 码（若有）→ 逐行读 UTF-16 输出 → 解析 `[handle:…]` 头 → 门禁（噪声/乱码/菜单/系统刷屏）→ 折叠与去重（逐字×N、成对双写、同句多形态、缺字变体）→ 折行拼接与说话人合并 → 交给翻译队列 → 悬浮窗流式显示。
- **同步**：每行解析与规则判定（纯函数）。
- **异步**：CLI 读循环、翻译请求、悬浮窗更新、状态事件。
- **失败点**：CLI 未安装；位数不匹配；钩子拿不到文本（引擎自绘文字）；未转区导致乱码；同句多线程抢占。
- **恢复**：回退 OCR；缺字版用只读内存子序列补全；失败时保留上一句译文并提示一次。

### F6 游戏内翻译（OCR 回退）与钩子查找

- **主流程**：OCR 模式下抬升游戏窗口（不抢焦点）→ 按区域截图（`PrintWindow` 优先，黑屏回退 `BitBlt`）→ WinRT OCR → 文本整理 → 与钩子路径共用清洗/去重/翻译链路。钩子查找器则是：采样线程栈收集候选 → 逐条试码 → 以「输出就是原文」为判据 → 命中写回该游戏。
- **同步**：截图与 OCR 调用（循环 0.9s 采样）。
- **异步**：采样、验证池、点击翻页（自动翻页辅助）。
- **失败点**：日语 OCR 组件缺失；窗口被遮挡导致合成缺图层；Debug 权限/硬件断点不可用。
- **恢复**：给出可点击的「去装日语组件 / 手动填码」指引；查找器可随时停止。

### F7 设置变更、窗口与退出

- **主流程**：设置页改动 → 校验 → 写 `state/settings.json`（去抖）→ 广播变更事件 → 各订阅方应用（主题/DWM、托盘开关、翻译参数、悬浮窗样式）→ 关闭窗口时：若开启托盘则隐藏继续运行，否则按序关停。
- **同步**：校验与内存生效（立即反馈）。
- **异步**：落盘、DWM 主题应用、托盘图标增删、悬浮窗重设。
- **关停顺序**：停止文本会话（detach + 关 CLI）→ 停止 OCR/翻译任务 → 停止下载监听 → 停止热键/托盘 → 停止本地资源服务 → 落盘 → 释放单实例互斥。
- **失败点**：磁盘写失败；托盘不可用；窗口已销毁仍收到事件。
- **恢复**：写失败保留内存状态并提示；事件推送对已销毁窗口静默丢弃。

## 线程 / 任务映射（P3 搬迁清单）

| 现线程名 | 来源 | 目标任务 | 取消方式 |
| --- | --- | --- | --- |
| `aurora-heartbeat` | `gl/api.py` | `session.heartbeat`（30s 周期） | TaskRunner 关停 |
| `aurora-session-<id>` | `gl/process.py` | `session.monitor:<game_id>`（1.5s 轮询） | 结束/超时 |
| `aurora-vntext-hook` | `gl/vntext.py` | `vntext.hook.read:<game_id>` | detach + 关管道 |
| `aurora-vntext-hookcode` | `gl/vntext.py` | `vntext.hook.code:<game_id>` | 一次性任务 |
| `aurora-vntext-ocr` | `gl/vntext.py` | `vntext.ocr.loop:<game_id>` | stop 事件 |
| `aurora-vntext-flush` | `gl/vntext.py` | `vntext.flush` | stop 事件 |
| `aurora-linetrans` | `gl/linetrans.py` | `translate.queue`（串行） | 队列哨兵 |
| `aurora-translate-q` | `gl/api.py` | `translate.prefetch`（简介翻译） | 队列哨兵 |
| `aurora-translate-all` | `gl/api.py` | `translate.batch` | 取消令牌 |
| `aurora-refresh-all` | `gl/api.py` | `metadata.refresh_all` | 取消令牌 |
| `aurora-steam-import` | `gl/api.py` | `metadata.steam_import` | 取消令牌 |
| （匿名）`_auto_search` | `gl/api.py` | `metadata.match:<game_id>` | 取消令牌 |
| `aurora-downloads` | `gl/downloads.py` | `downloads.watch`（周期） | stop 事件 |
| `aurora-hooksearch` / `aurora-hooksearch-advance` | `gl/api.py` | `hooksearch.run` / `hooksearch.advance` | stop 事件 |
| `aurora-tray` / `aurora-tray-supervisor` | `gl/tray.py` / `main.py` | `appshell.tray`（平台线程） | 退出 |
| `aurora-hotkeys` | `gl/hotkey.py` | `appshell.hotkeys`（平台线程） | 退出 |
| `aurora-overlay-resize` | `gl/overlay.py` | `overlay.border` | 一次性 |
| `aurora-drop-bind` | `main.py` | `appshell.drop_bind` | 一次性 |

## 失败路径汇总

| 失败 | 表现 | 期望行为 |
| --- | --- | --- |
| 库文件损坏 | 启动时报 JSON 解析失败 | 使用最近备份恢复并保留损坏文件；界面提示 |
| 迁移失败 | 启动中断 | 回滚到 v1 文件，按旧格式继续运行并提示 |
| 事件推送时窗口已销毁 | `evaluate_js` 抛异常 | 静默丢弃，不写日志噪声 |
| 翻译接口超时 | 悬浮窗停在上一句 | 保留上句译文 + 一次提示；下次台词重置状态 |
| CLI 提前退出 | 无输出 | 状态置为不可用，推 `vntext:status`，可用 OCR 继续 |
| 磁盘写失败 | 设置/素材落盘失败 | 内存状态保留，提示用户，诊断包记录 |

## Evidence vs assumptions

- **证据**：线程名、轮询间隔（1.5s / 30s / 0.9s）、时序约束（先 attach 后发码）全部来自当前实现。
- **假设**：事件推送频率上限为「每秒几条」（翻译流式 + 状态），因此 UI 线程排队足够；若出现高频事件，
  按 `10` 的热点 H4 合并后再推。
- **不确定**：本地资源服务放在哪个阶段启动（在窗口创建之前）未实测双内核时序 → P5 验收覆盖。

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| TaskRunner 成为新瓶颈 | 所有任务共用一个线程池 | 按域分配有界池（IO 密集 / CPU 密集分开），并设队列上限 |
| 关停顺序不完整 | 残留子进程或线程 | 关停清单进代码评审；测试断言「退出后无子进程」 |
| 事件风暴 | 快速翻页时每句多条事件 | 合并同类事件（节流 100ms），保证 seq 单调 |

## Recommended next skill

`deployment-view-writer` → 见 [`09-deployment-view.md`](09-deployment-view.md)。
