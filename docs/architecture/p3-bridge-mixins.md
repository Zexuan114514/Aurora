# P3.1 交付记录：桥接层开始拆 mixin

## Summary

P3 的第一刀：把 `gl/api.py` 里两组自包含方法搬进 `aurora/ui/bridge/`，用 **mixins + 继承**保持
「pywebview 只暴露顶层方法」这一硬约束（ADR-0006）。方法体逐字未改，契约零漂移。

| 项 | 之前 | 之后 |
| --- | --- | --- |
| `gl/api.py` | 2232 行 | 1993 行（-239） |
| `aurora/ui/bridge/window.py` | — | 136 行 / 10 个方法：`window_cmd`、拖拽（`drag_*`）、缩放（`resize_*`）、`apply_window_theme`、`apply_window_icon`、`minimize_to_tray`、`set_tray` |
| `aurora/ui/bridge/shell.py` | — | 158 行 / 12 个方法：`open_*`（URL / 目录 / 语言设置 / 源站搜索 / Textractor 页）、`reveal`、`pick_*`（exe / 下载目录 / LEProc / TextractorCLI） |
| 公开桥接方法 | 106 | 106（`Api` 继承两个 mixin，名字与签名逐一比对一致） |
| 前端调用点 / 事件主题 | 96 / 14 | 96 / 14 |

## 关键实现

1. **继承而不是组合**：`class Api(WindowBridgeMixin, ShellBridgeMixin)` —— pywebview 只认 `js_api`
   对象的顶层方法，组合对象会丢方法；mixin 让方法仍然挂在同一个实例上。
2. **契约守卫要看得见继承**：`tools/checks/common.class_methods` 现在会静态解析基类
   （同文件基类 + `from a.b import Base` 形式），所以快照比对覆盖 mixin 里的方法，
   否则会误报「公开方法 84 个，快照 106」。
3. **桥接层规则**：`check_layers` 新增「`aurora/ui/bridge/*` 不得直接 import `aurora.infra`」，
   并记录仍然借道 `gl` 遗留模块的文件（当前 2 个，P3.2 收口）。
4. **运行时冒烟**：构造 `Api()`（沙盒数据目录）验证 `Api.window_cmd.__qualname__` 落在 mixin 上、
   `drag_start` / `resize_start` / `minimize_to_tray` / `window_cmd` / `pick_executable` / `open_data_dir`
   都能优雅返回（无窗口时不抛异常），`shutdown()` 正常收尾。

## 验收证据（2026-09-20）

| 检查 | 结果 |
| --- | --- |
| `python tools\checks\check_contract.py` | PASS：公开方法 106、前端调用点 96、事件 14，与快照零差异 |
| `python -m pytest` | **26 passed** |
| `python tools\checks\run_all.py` | **6/6**（含分层守卫：桥接层未直接 import infra） |
| 运行时冒烟 | `Api` 继承两个 mixin；6 个被搬方法的调用返回符合预期；`shutdown()` 后沙盒 `state/` 正常 |

## 还没做的（P3.2）

- 剩余 ~84 个方法按域继续拆：`library`（增删改查/分类）、`metadata`（搜索/匹配/翻译）、
  `launch`（启动/会话）、`vntext`（翻译面板与钩子查找）、`downloads`（获取游戏）、`settings`（设置页）。
- 用 `TaskRunner`（`aurora/app/ports.py` + `aurora/infra/tasks.py`）收掉 20 个具名线程，
  组件间改走 `EventBus` 而不是构造器回调。
- `aurora/ui/bridge/*` 里 `from gl import config/process/vntext` 的临时依赖收口到
  `aurora.platform` / `aurora.infra`（同时把 `gl/winapi.py` 搬进 `aurora/platform/`）。

## P3.2 追加：设置 / 资料源 / 站点 / 下载 / 转区 / 网络（2026-09-20）

| 项 | 结果 |
| --- | --- |
| 新 mixin | `aurora/ui/bridge/settings.py`，223 行 / **19 个方法**：`set_setting`、资料源管理 7 个、站点管理 4 个（含 `_sites`）、下载 2 个、转区 2 个、网络 3 个 |
| `gl/api.py` | 1993 → **1808 行**（累计 2232 → 1808，-424） |
| `Api` 基类 | `Api(WindowBridgeMixin, ShellBridgeMixin, SettingsBridgeMixin)` |
| 契约 | 公开方法 **106** / 前端调用点 96 / 事件 14，与快照零差异 |
| 验收 | `pytest` 26 passed、`run_all` 6/6；运行时冒烟：17 次调用全部返回预期结构（`list_sources`/`_sites` 返回列表属设计），无 `NameError`/`AttributeError` |

> 这批方法里含 `test_network`（会真连五个端点）与 `test_source`（联网），离线冒烟只覆盖本地分支，
> 联网行为仍由 `tools/net_probe.py` / `tools/test_sources.py` 回归。

**P3.3 待办**：`library`（约 30 个方法：增删改查 / 分类 / 素材 / 导入导出）、`metadata`（搜索与翻译）、
`launch`（启动与会话）、`vntext`（翻译面板与钩子查找）、`downloads`、以及 `TaskRunner` + `EventBus` 收线程；
最后把桥接层对 `gl` 的临时依赖收口到 `aurora.platform` / `aurora.infra`。

## P3.3 追加：游戏库 / 分类 / 素材 / 导入导出（2026-09-20）

| 项 | 结果 |
| --- | --- |
| 新 mixin | `aurora/ui/bridge/library.py`，491 行 / **37 个方法**：游戏增删改（11）、分类书架（11）、封面/背景/图标素材（11）、库导入导出与扫描（4） |
| 新共享模块 | `aurora/ui/bridge/shared.py`（98 行）：`_public()` 投影、`_resolve_note`、`NOTES`、`IMAGE_EXTS`、`LAUNCHABLE_EXTS` —— 它们是 mixin 之间的公共依赖，留在 `api.py` 会造成循环 import |
| `gl/api.py` | 1808 → **1292 行**（累计 2232 → 1292，-42%），类内剩余 70 个方法 |
| `Api` 基类 | `Api(WindowBridgeMixin, ShellBridgeMixin, SettingsBridgeMixin, LibraryBridgeMixin)` |
| 契约 | 公开方法 **106** / 前端调用点 96 / 事件 14，零差异 |
| 验收 | `pytest` 26 passed、`run_all` 6/6；运行时冒烟：**33 个被搬方法逐一调用，零异常** |

**做法上的一条经验**：第一版用「行号 + 偏移」批量剪切，偏移算错（净减 83 行却按 87 算）把 `_emit`
的 `def` 行切掉了——虽然文件仍能解析，但方法静默消失。改成**按原文精确文本删除**（`str.replace(text, "", 1)`
并断言 `def _emit` 仍在）后一次通过。P3.4 继续搬时沿用这个做法。

**P3.4 待办**：`metadata`（搜索 / 匹配 / 简介翻译）、`launch`（启动、会话、恢复）、`vntext`（翻译面板 /
钩子查找 / 悬浮窗动作）、`downloads`、`bootstrap` 聚合；再加 `TaskRunner` + `EventBus` 收掉 20 个具名线程，
并把桥接层对 `gl` 的临时依赖（config / process / vntext / downloads / locale / netproxy）收口。

## P3.4 追加：元数据 + 游戏内翻译 / 钩子查找 / 悬浮窗（2026-09-20）

| 项 | 结果 |
| --- | --- |
| 新 mixin | `aurora/ui/bridge/metadata.py`（18 个方法：重抓 / Steam 导入 / 搜索匹配 / 简介翻译）<br>`aurora/ui/bridge/vntext.py`（38 个方法：翻译面板状态 / 钩子查找器 / 悬浮窗动作 / 术语表） |
| `gl/api.py` | 1292 → **309 行**（累计 2232 → 309，-86%），类内只剩 **14 个方法**：`__init__` / `bootstrap` / `scan_downloads` / `set_game_locale` / `shutdown` / `launch` / `_locale_command` / `_on_game_found` / `_on_game_exit` / `stop` / `_start_heartbeat` / `_beat` / `_recover_sessions` / `_emit` |
| `Api` 基类 | 6 个 mixin：window / shell / settings / library / metadata / vntext |
| 契约 | 公开方法 106 / 前端调用点 96 / 事件主题 14，零差异 |
| 验收 | `pytest` 26 passed、`run_all` 6/6；运行时冒烟 **37 个方法**，其中 `scan_steam` 读到本机 Steam 库、`test_translation` 真连免费接口返回译文 |

**冒烟抓到两个真问题（都已修）**：

1. **函数内相对 import 在 mixin 里解析错**：`from . import steamlib` / `from .sources import net` /
   `from . import winapi` 原本在 `gl/` 里合法，搬进 `aurora/ui/bridge/` 后会去找 `aurora.ui.bridge.*` →
   `ImportError`。三处改成绝对路径（`from gl import steamlib` 等），并在 `check_layers` 里加硬规则：
   桥接 mixin 出现任何相对 import 直接判失败。
2. **契约守卫的扫描范围要跟着方法走**：`_emit(...)` 与悬浮窗动作字符串搬进 mixin 后，
   「事件主题 / 悬浮窗动作」检查只扫 `gl/api.py` 就全红。现在 `check_contract` 与 `update_contract`
   都会扫描整个 `aurora/ui/bridge/`。

**P3.5（最后一刀）**：把剩下 14 个方法按 `launch`（启动 / 会话 / 恢复）+ `downloads` + `bootstrap`
拆完，然后做 `TaskRunner` + `EventBus`（收掉 20 个具名线程、去掉构造器回调），
并把桥接层对 `gl` 的临时依赖收口到 `aurora.platform` / `aurora.infra`。

## P3.5 追加：启动 / 会话 / 下载拆完，`api.py` 变成薄壳（2026-09-20）

| 项 | 结果 |
| --- | --- |
| 新 mixin | `aurora/ui/bridge/session.py`（176 行 / 10 个方法）：`scan_downloads`、`set_game_locale`、`launch`、`_locale_command`、`_on_game_found`、`_on_game_exit`、`stop`、`_start_heartbeat`、`_beat`、`_recover_sessions` |
| `gl/api.py` | 1292 → **160 行**（起点 2232 → 160，**-93%**），类内只剩 4 个方法：`__init__`（装配）、`bootstrap`（首屏聚合）、`shutdown`（退出收尾）、`_emit`（唯一事件出口） |
| `Api` 基类 | 7 个 mixin（window / shell / settings / library / metadata / vntext / session） |
| 契约 | 公开方法 106 / 前端调用点 96 / 事件主题 14，零差异 |
| 验收 | `pytest` 26 passed、`run_all` 6/6；冒烟 11 个启动/会话方法零异常（`bootstrap`、`scan_downloads`、`launch`、`_on_game_exit`、`_recover_sessions` 等） |

**测试又抓到一个真缺陷**：`session.py` 少了 `from aurora.domain import session_rules`——
方法搬出后内联公式仍在调用 domain 函数，但导入没跟着走。`test_session_rules_wired_into_process_and_api`
正好断言「有且只有一处调用会话公式、且该模块确实 import 了它」，当场报红；修完并让断言跟随搬迁
（不再写死 `gl/api.py`），以后同类搬迁不会漏导入。

**P3.6 剩下**：`TaskRunner` + `EventBus`（替掉 20 个具名线程与构造器回调）、桥接层对
`gl` 的临时依赖收口到 `aurora.platform` / `aurora.infra`（含 `gl/winapi.py` → `aurora/platform/`）、
`app/services` 承接 mixin 里的编排逻辑（现在 mixin 仍是「方法体原样搬家」，P3.6 才真正服务化）。

## P3.6 第一批：任务执行器 / 事件总线 / 平台层落地（2026-09-20）

| 项 | 结果 |
| --- | --- |
| `aurora/infra/tasks.py` | `TaskRunner`：命名任务、有界线程池、协作取消令牌、`active()`/`stats()`/`shutdown()`；同名任务重复提交先取消旧的 |
| `aurora/app/events.py` | `EventBus`：`{topic, seq, ts, payload}` 信封、`"*"` 通配订阅、取消订阅、`recent()` 诊断缓冲、订阅者异常隔离（错误进 `errors`） |
| `aurora/platform/winapi.py` | 从 `gl/winapi.py` 原样搬入（332 行）；`gl/winapi.py` 变 36 个名字的转发 shim；`main.py` 与 `ui/bridge/window.py` 改用平台层路径，并去掉一处函数内相对 import |
| 测试 | `tests/test_task_runner.py` 5 项：提交/活跃列表、取消令牌、事件信封与 `seq` 单调、退订与通配、订阅者异常隔离 |
| 验收 | `pytest` **31 passed**、`run_all` 6/6、契约仍 106/96/14 零差异 |

**P3.7 待办（真正的行为改造）**：

1. 把 20 个具名线程逐个交到 `TaskRunner`（心跳、会话监控、CLI 读循环、OCR 循环、翻译队列、
   批量任务、下载监听…），退出时统一 `shutdown()`，并把组件回调（`on_line`/`on_status`/`on_found`/`on_exit`）
   改成 `EventBus` 订阅。
2. 桥接 mixin 退化为「参数整形 + 调服务 + 推事件」，编排逻辑进 `app/services/*`。
3. 继续收口 `gl` 依赖：`config` → `aurora.infra.store.paths`、`process`/`vntext`/`downloads`/`locale`/`netproxy`
   按分层归位（`platform` 或 `infra`），每步都用契约守卫 + 冒烟验证。

## P3.7 执行记录（2026-09-20，四个提交）

| 批次 | 提交 | 内容 |
| --- | --- | --- |
| a | `f9f69a6` | `Api` 起引入 `TaskRunner` + `EventBus`；心跳收编为 `session.heartbeat`；`_emit` 走总线（新增 `_dispatch_event` 作唯一前端出口）；修 `winapi` 相对 import 与线程池非 daemon 两个真 bug |
| b | `652ca50` | 9 处长驻线程 → `default_runner().spawn()`：会话监控 / 翻译队列 / 下载监听 / 托盘 / 热键 / 悬浮窗 / CLI flush / 拖放绑定 / 托盘看护 |
| c | `23a3a6c` | 剩余 8 处：vntext 的 hook 读循环 / 专码发送 / OCR 采样；metadata 的重抓 / Steam 导入 / 自动匹配 / 翻译队列 / 批量翻译；hooksearch 与两处翻页点击。**裸线程清零**（只剩 runner 自身与 state 单写者） |
| d | `b5d9b56` | 回调改事件：`linetrans`/`vntext`/`process`/`downloads` 无回调时向 `default_bus()` 发布内部主题（`engine.*`），`Api` 改为订阅 6 个内部主题；`overlay.on_action` 是请求-响应语义，保留回调 |

**结果**：`gl/` + `aurora/` + `main.py` 里的裸 `threading.Thread` 只剩 2 处（`aurora/infra/tasks.py` 的 runner 与
`aurora/infra/store/state.py` 的单写者），其余全部是命名任务（`TaskRunner.submit` / `spawn`）。
桥接层 0 处 `aurora.infra` 依赖（改用注入的 `self._tasks`），`check_layers` 全程无违规。

**每批验收**：`pytest`（33 passed，含 TaskRunner 的 spawn/取消/单例用例）、`run_all` 6/6、
契约 106 公开 / 42 内部 / 96 前端调用点 / 14 事件主题零差异、`session_probe` 与 `vntext_probe` 全部通过、
总线冒烟（`engine.vntext_status` → `vntext:status`、`engine.downloads_status` → `downloads:status`、
`engine.translate(done)` → `vntext:line(translated)`、`engine.session_*` 对未知游戏不崩）。

## P3.8 待办（剩余工作，按优先级）

1. **服务化**：mixin 里的编排逻辑搬进 `aurora/app/services/`（`settings` / `library` / `metadata` / `launch` / `vntext`），
   mixin 退化成「参数整形 → 调服务 → 推事件」；建议先做 `settings`（纯校验与 CRUD，风险最低）再做 `library`。
2. **依赖收口**：桥接层仍 `from gl import config, process, vntext, downloads, locale, netproxy, steamlib, think`
   等 8 个文件（`check_layers` 会实时列出）；按 `config` → `aurora.infra.store.paths`、
   `winapi` 已就位的模式逐个搬到 `aurora/platform` / `aurora/infra` 并留转发 shim。
3. **收尾**：重跑真机矩阵（`vntext_live` hook 与 OCR、`e2e` 90 项、`visual`）、重建 `Aurora.exe`、
   更新 README 的目录结构与自检脚本小节。

### P3.8 执行记录

| 批次 | 提交 | 内容 | 验收 |
| --- | --- | --- | --- |
| a | `3b4e300` | **服务化第一刀**：`aurora/app/services/settings.py`（设置快照 / 资源站 CRUD / 资料源配置）；`aurora/ui/bridge/settings.py` 的 11 个方法退化为一行的 `self._settings.xxx` 转发；`Api` 装配 `SettingsService(self._library, self._sources)` | `pytest` 33 passed、`run_all` 6/6、契约零差异、冒烟全 ok |

> 这一刀又验证了契约守卫的价值：转发方法最初丢掉了返回标注（`-> dict` / `-> list[dict]`），
> `check_contract` 立刻报「参数/返回与快照不一致」，补回标注后通过。

**下一刀（P3.8-b）建议**：同法下沉 `library`（游戏 CRUD / 分类 / 素材，约 490 行 mixin）
→ `aurora/app/services/library.py`，再下沉 `metadata` / `launch` / `vntext`；随后处理依赖收口
（桥接层目前仍 `from gl import config, process, vntext, downloads, locale, netproxy, ...`，
`check_layers` 会实时列出清单）。

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 继承让「方法在哪」变模糊 | 读 `gl/api.py` 看不到全部方法 | 契约快照 + `update_contract.py --write` 的输出会列全量方法；mixin 头部写明范围 |
| mixin 之间互相调用 | 搬第二刀时可能出现跨 mixin 调用 | 允许（同一个 `self`），但禁止跨 mixin 访问对方的私有属性；需要共享状态时上移到 `Api.__init__` |
| 临时 `gl` 依赖 | 桥接层仍 import 遗留模块 | 已在 `check_layers` 里显式列出，P3.2 归零 |

## P3.9 依赖收口与收尾（2026-09-20）

| 批次 | 内容 |
| --- | --- |
| P3.9 二批 | `screencap`/`ocr` → `aurora/platform`；`netproxy` → `aurora/infra` |
| P3.9-b/c/d/e | `linetrans`、`downloads`、`process`、`vntext`（1358 行文本引擎）→ `aurora/infra` |
| P3.9-f | `tray`/`hotkey` → `aurora/platform` |
| P3.9-g | `overlay` → `aurora/ui`；`config` → `aurora/infra`（最纠缠的模块） |
| P3.9-h | `FileDialogPort` + `infra/dialogs.WebviewFileDialog`，桥接层不再直接调窗口对话框 |

**机制改进**：`gl/` 的转发壳从「逐个复制名字」改成 **`sys.modules` 透明模块别名**——
读写模块级状态与给模块打补丁（如探针模拟「没装日语」时改 `ocr._langs`）都作用到同一份实现上。

**搬迁引入的两个回归（都被真机矩阵抓到并修复）**：

1. `config` 搬到 `infra` 后仍按 `__file__` 推 `PKG_DIR/WEB_DIR` → 指向不存在的 `aurora/infra/web`，
   用户启动会看到空白窗口（`e2e` 第一项 JS 即 null）。改为按项目根推导，保持 `PKG_DIR = 项目根/gl` 的语义。
2. `overlay` 搬到 `ui` 后 `HTML_PATH` 同样按 `__file__` 推 → 悬浮窗创建失败（日志 `overlay html missing`）。
   改为统一走 `config.WEB_DIR`。

**收尾验收（2026-09-20）**：`e2e` **90/90**、`theme_probe` / `download_probe` / `locale_probe` / `net_probe` / `session_probe` / `vntext_probe` 全部通过、`visual` 背景缩放与复位正常、`pytest` 41 passed、`run_all` 7/7、契约 106/42/96/14 零差异；`Aurora.exe` 重建后实测出现可见窗口「Aurora 游戏启动器」1356×816。

## P3.10 「找钩子」重做：签名播种 + 寄存器偏移（2026-09-20）

### 现场结论（アマカノ３ / Artemis-Emote 真机）

1. **采样式收集对「自绘文字」引擎无效**：文本指针只在绘制调用的一瞬间存在于寄存器/栈上，
   50ms 一次的全线程采样永远撞不上 —— 12 秒采到的 600~1300 条候选**全是噪声**
   （`igd11dxva64.dll` 字符串表、GPU 驱动栈帧等），没有一条像台词。
2. **Textractor 自带钩子在这类引擎上完全空转**：它的 108 个 API 钩子（GDI/User32）都注入成功，
   但游戏用 D3D11 自绘文字，一个字都不经过它们。
3. **官方的做法**（`texthook/hookfinder.cc` 的 `SearchForHooks`）是：把候选函数全挂上 →
   在每个挂钩点扫 `[-128, +72]` 的栈槽 → 谁指向一段文本就记成
   `(挂钩地址, 数据偏移, padding)`；x64 上那些「栈槽」其实就是**存根压栈保存的寄存器**。
4. **H-code 的 `#偏移` 语义**（源码 `hookcode.cpp` + `texthook.cc` 的 x64 存根）：
   `dwDataBase` = 挂钩点的原始 RSP；`#N`（N<0 时解析器再 `-=4`）→ 读 `[RSP+N]`。
   存根按 `rflags/rax/rbx/rcx/rdx/rsp/rbp/rsi/rdi/r8…r15` 顺序压栈，于是
   「真实 -0x70 = R12」要写成 `-6C`；RDX 是 `-24`、RCX 是 `-1C`、RDI 是 `-44`。

### 现在的实现

| 步骤 | 做法 | 代码 |
| --- | --- | --- |
| ① 定位可疑函数 | 序言特征码扫描（内存 + **磁盘 PE 镜像**） | `hookfinder.scan_text_signatures` |
| ② 试数据偏移 | 按 `HOOK_OFFSETS` 顺序发 H-code（R12→RDX→RCX→R8/R9→RDI/RSI→…→影子空间） | `hookfinder.HOOK_OFFSETS` |
| ③ 验证 | 发码 → 代点一次 → 看这条线程有没有吐出像台词的文本（OCR 文本只做参考） | `HookSearchService._hooksearch_try` |
| ④ 落盘 | 命中即写 `vntext_hook` 并发给正在跑的 CLI | 既有 `_hooksearch_try` |

**为什么必须扫磁盘**：Textractor 在某函数入口装过钩子后，那几字节被改成跳转 ——
同一局里再扫内存就**找不到这个函数了**（真机实测：候选从 `Amakano3.exe+0x1b1f70` 变成完全不命中）。
磁盘镜像不会被改，所以按 PE 节表把文件偏移换算成 RVA 再取候选。

**验收（真机，pid 17164 / アマカノ３）**：

* 服务级：候选 1 命中 —— `HS65001#-6C@1B1F70:Amakano3.exe`，库里随即写入这条码；
  其间 Textractor 打出 `[2:430C:…:UserHook:HS65001#-6C@1B1F70:Amakano3.exe] 詩夢「……これで、落ちたら」`。
* 界面级：真窗口 + 真页面，面板实时跟着事件走 `[识别台词] → [验证候选] → [成功]`，
  提示「找到了：HS65001#-6C@1B1F70:Amakano3.exe（已存为该游戏专用码）」。
* 离线：`pytest` 46 passed（新增 `tests/test_hook_offsets.py` 锁偏移语义）、`run_all` 7/7。

### 顺带修掉的三件事

1. **悬浮窗挡点击**：查找期间把悬浮窗临时设成穿透（`persist=False`），结束还原 ——
   否则置顶的悬浮窗会盖住代点位置，`advance()` 的安全策略会拒绝点击。
2. **伪线程污染**：Textractor 的「剪贴板/控制台/默认」线程会把剪贴板内容当台词
   （真机实测：用户刚复制的链接）—— 验证阶段一律跳过。
3. **调试器安全脱离**：事件处理一旦抛异常就漏掉 `ContinueDebugEvent`，脱离时那个未处理的
   单步异常会转交给游戏本体（アマカノ３ 因此崩过两次，WER 异常码 `0x80000004`）。
   现在每个事件都包 `try/finally`，脱离前先 drain（排空）再拆断点。

### P3.10-b 依赖收口：`memmatch` / `hookfinder` 归位

| 变化 | 说明 |
| --- | --- |
| `gl/memmatch.py` → `aurora/platform/memmatch.py` | 内存扫描原语（只读；缺字补全 / OCR 吸附） |
| `gl/hookfinder.py` → `aurora/platform/hookfinder.py` | 找钩子原语（签名播种 + 调试器断点 + 差分定位） |
| `gl/*.py` 保留 12 行透明别名壳 | 老脚本（`tools/hooksearch_probe.py`、`tools/vntext_probe.py`…）与 `gl/api.py` 无需改动 |
| 调用方改走新路径 | `aurora/app/services/hooksearch.py` 直接用 `aurora.platform`；`aurora/infra/vntext.py` 的 3 处懒加载改 `aurora.platform.memmatch` |

验收：`run_all` 7/7（架构基线里按 `superseded_by` 的方式登记了搬家）、`pytest` 46 passed、
自进程冒烟 `memmatch.candidates(os.getpid(), …)` 命中、`gl.memmatch is aurora.platform.memmatch`
（透明别名生效）。

### P3.10-c 用户实测反馈：面板触发时全失败（2026-09-20 21:00）

用户从翻译面板点「找不到文本？开始侦测」时，三处场景都失败（「采样到的候选都不像台词」），
而我从终端跑同样的服务却是好的。现场日志给出了四个叠加原因，全部已修：

| # | 现象 | 真因 | 修法 |
| --- | --- | --- | --- |
| 1 | 12 个偏移全部「读不到文本」 | 候选线程取样走的是 `status()["threads"]`，那是**给界面看的、只留前 12 条**；用户库里带着一条每帧吐乱码的坏码，`_seen` 堆了几百条垃圾线程，候选线程（count=1）永远进不了前 12 | 新增 `VnTextEngine.hook_sample_for(code)`：扫**全量** `_seen`，并按 `last_seen` 取**最新**那条（Textractor 每翻一页换一个 handle，按长度取会一直返回旧句） |
| 2 | 游戏被拖慢，点击后几秒才渲染 | 那条坏码挂在绘制热函数（`emotedriver+0x38A78`，每帧上千次调用）上，Textractor 每次调用都走一遍 Send | 找钩子前先切**干净会话**（`_hooksearch_clean_session`：detach → 不带用户码重新 attach），找不到新码再把原码还回去 |
| 3 | 明明可用的码被判失败 | 每次候选只代点 1 次；`HS65001#-6C`（R12）只在部分渲染路径上带文本，单次点击常常错过 | 每个候选代点 2 次（`clicks=2`） |
| 4 | 确认轮判 0/2（已命中过却被丢弃） | 取样取「最长」——新句子比旧句子短时判成「没变化」 | 取样改取「最新」（见 #1） |

**加固**：候选命中后要过一轮**确认轮**（再点两下仍能出文本）才落库，避免存下只在特定场景
生效的码；全试完仍没有稳定的，就退回「偶尔能用」的那条。

**真机验收（用户在跑的现场、且库里带着坏码）**：修复后连续三次跑通 ——
`HS65001#-3C`（27 秒/7 候选）→ `HS65001#-24`（5 秒/2 候选，确认轮 1/2）→
`HS65001#-6C`（第一个候选即命中、确认通过）。另清掉库里那条坏码
`HS65001#20@38A78:emotedriver.dll`（实测只吐 `�$�8` 这类乱码），自动规则随即带出
正确的 `HS65001#-6C@1B1F70:Amakano3.exe`。

**回归测试**：`tests/test_hook_sample_for.py`（5 条）锁住「界面投影会截断到 12 条」
「取样扫全量」「raw 兜底」「取最新而非最长」「跳过伪线程」；`pytest` 51 passed。

### P3.10-d 设置不保存：服务方法改名漏改桥接（2026-09-20 22:30）

用户实测：设置页改完重启又回到旧配置。取证（对比 `state/backup/settings-pre-write-*`）
显示文件里**部分**改动是落了盘的，于是转向调用链，最后定位到：

| 项 | 内容 |
| --- | --- |
| 症状 | 设置页任何「普通设置」（模糊/饱和度/主题/强调色…）改完不生效、不落盘 |
| 真因 | P3.8-a 把 `SettingsService.set_setting` 改名成 `set`，桥接层 `aurora/ui/bridge/settings.py` 还在调 `self._settings.set_setting(...)` → 每次保存抛 `AttributeError`（前端只 toast 一下，日志里也没有痕迹） |
| 为什么没被守卫拦住 | `check_contract` 只看桥接层自己的方法名与签名（改名不在它视野里）；「启动冒烟」只构造 `Api()` 不调方法 |
| 修法 | 服务方法名改回 `set_setting`（公开桥接契约名不变） |
| 新守卫 | `tools/checks/check_bridge_targets.py`：解析桥接 mixin + `gl/api.py` 里所有 `self._服务.方法(...)`，对着服务类（`SettingsService`/`LibraryService`/`MetadataService`/`VnTextService`/`HookSearchService`/`LaunchService`/`TranslationService` + 引擎/悬浮窗）的属性表核一遍。当前核对 **109 处转发全部存在**，已并入 `run_all`（第 8 项检查） |

**验收**：`_sandbox/settings/settings_probe.py` 三段全绿 ——
① 走桥接写三个探针键 → 内存与文件一致；② 新进程重启读回来仍存活；
③ **真实界面**：把设置页模糊滑杆改成 7 → `settings.json` 里 `blur = 7`。
`run_all` 8/8、`pytest` 51 passed。

## P4.1 前端 ES 模块化第一步（2026-09-20 22:45）

**先确认了 P4 的前置条件**：`_sandbox/p4/check_protocol.py` 实测主窗口 `location.href` 是
`http://127.0.0.1:55697/index.html`（pywebview 检测到本地 URL 就自动起了内置静态服务器），
所以 **ES 模块今天就能用**，不必等 P5 的自建资源服务。

| 改动 | 内容 |
| --- | --- |
| `gl/web/app.js` | 从 IIFE 改成 **ES 模块**（去掉外层包装、删掉本地 `api()/call()`）；版本 3688 → 3922 行，行为零变化 |
| `gl/web/app/core/api.js` | 新增：桥接唯一出口（`bridge()` / `bridgeReady()` / `call()`）—— 全前端只有这里摸 `window.pywebview.api` |
| `gl/web/index.html` | 注入的脚本改成 `type="module"` |
| `tools/build_exe.py` | 前端清单新增 `WEB_MODULE_DIRS = ("app",)`，模块树按目录整棵打进包（用户素材目录仍然排除） |
| `tools/checks/baseline.json` | 登记 `gl/web/app/core/api.js`、刷新 `app.js` 行数 |

**为什么敢动**：`tools/e2e.py` 会真起窗口、真点按钮、真校验 90 项；改造前后各跑一次，
`e2e` **90/90**、`tools/visual.py` 的 `errors=[]`（没有 JS 报错）、`run_all` 8/8。

**下一刀（P4.2）**：把状态与实体更新收进 `gl/web/app/core/store.js`（现在散在 3900 行的 `state`
与各处 `render()`），再按 `views/{hall,game,settings,categories}` 拆；`window.__aurora`
（`ring()`/`layout()`）与 `window.__auroraErrors` 这两个稳定测试面必须原样保留。

### P4.2 状态与实体更新收进 `core/store.js`（2026-09-20 23:05）

| 改动 | 内容 |
| --- | --- |
| `gl/web/app/core/store.js` | 新增：唯一 `state`（活绑定导出）+ 实体更新 helper：`findGame` / `currentGame` / `setBusy` / `upsertGame` / `pushGame` / `patchGame` / `replaceGames` / `replaceShelves` |
| `gl/web/app.js` | 删掉本地 `state`（24 行）与 `currentGame` 的实现，改为 import；**事件处理里的实体更新全部改走 helper**（`game:updated/stopped/running`、`games:imported`、`metadata:searching/notfound/error`、`refreshLibrary`、书架刷新） |
| 约束 | 视图仍可直接**读** `state.x`；但**写实体必须**经过 store helper —— 后面拆 `views/` 时不会出现两边各改一半 |

改完 `app.js` 3889 行（比 P4.1 少 33 行），`run_all` 8/8、`e2e` **90/90**、
`tools/visual.py` 无 JS 错误。

**下一刀（P4.3）**：按视图拆 `gl/web/app/views/{hall,game,settings,categories}.js`
（每个视图只导出 `mount`/`render`，跨视图状态一律走 store），`window.__aurora.ring()/layout()`
改成从 `views/hall.js` 取数，测试面签名不变。

### P4.3-a 共享 DOM 层 `core/dom.js`（2026-09-20 23:25）

拆视图之前先把**所有视图都要用的那张元素表**搬出去，否则每个 view 都会反向
import 主模块，变成循环依赖。

| 改动 | 内容 |
| --- | --- |
| `gl/web/app/core/dom.js` | 新增：`missingIds`（HTML/JS 对不上时记一笔，最终进 `window.__auroraErrors`）、`$`、`el`（启动时一次性抓好的元素表，46 个元素） |
| `gl/web/app.js` | 删掉本地 `$`/`missingIds`/`el`（53 行），改成 `import { $, el, missingIds } from "./app/core/dom.js"`；`app.js` 3889 → 3838 行 |

验收：`run_all` 8/8、`e2e` **90/90**（含「缺元素上报」相关断言）。

**下一刀（P4.3-b）**：给 store 加一个变更通知（`onChange`/`notify`）后，把
`views/categories.js`（书架/选择/状态那段 `togglePick`…`setGameStatus`，约 90 行）
整块搬出去：视图只 import `core/{api,dom,store}`，不再反向依赖主模块；
`window.__aurora.ring()/layout()` 保持不变。

### P4.3-b 第一块视图 `views/categories.js`（2026-09-20 23:50）

书架 / 多选 / 游戏状态这一段（`setOrganizing` … `setGameStatus`，103 行）整块搬进
`gl/web/app/views/categories.js`。

| 设计点 | 做法 |
| --- | --- |
| 不反向依赖主模块 | 视图只 import `core/{api,dom,store}`；主模块的渲染与提示函数（`render`/`renderCatBar`/`applyShelfPayload`/`setScope`/`renderDetail`/`toast`/`modal`/`cssEscape`/`STATUS_LABEL`）由 `createCategoriesView(ctx)` **注入**——所以不会出现「视图 import 主模块」的循环依赖 |
| 调用点零改动 | 主模块里 `const { setOrganizing, togglePick, … } = createCategoriesView({…})`，原有 `onclick` 绑定一个字没改 |
| 守卫跟着升级 | `check_contract` 的「前端调用点」与 `check_layers` 的「不许绕过 `call()`」都从只看 `app.js` 改成扫**整棵前端模块树**（`gl/web/app/**/*.js`）——否则视图里的 7 个调用点会被判成「不再调用」 |

结果：`app.js` 3838 → 3744 行；`run_all` 8/8（前端调用点 96 个，全部有后端实现）、
`e2e` **90/90**。

> 备注：第一次 e2e 跑出 88/90，两项失败是「背景图已应用」（要联网取 Steam 封面）与
> 「拖拽缩放窗口」（鼠标拖拽时序）——重跑即 90/90，属偶发，与本次改动无关。

**下一刀（P4.3-c）**：同法搬 `views/hall.js`（环/布局 + `window.__aurora.ring()/layout()`
的取数逻辑，测试面签名不变），再是 `views/settings.js`、`views/vntext.js`。

### P4.3-c 设置视图 `views/settings.js`（2026-09-21 00:15）

设置页的开关与分页导航（`setSettingsTab` / `openSettings` / `closeSettings` /
`refreshSettingsPanes`，40 行）搬进 `gl/web/app/views/settings.js`。

**踩到的坑（值得记一笔）**：ctx 一开始直接传函数引用 ——

```js
createSettingsView({ render, applySettingsToUi, …, closeAll })
```

其中 `closeAll` 是 **`const` 箭头函数**、定义在工厂调用**之后**，于是模块初始化时
取它直接踩 TDZ：整页脚本挂掉，e2e 掉到 **3/13**（连「空库显示空状态」都过不了）。

修法：ctx 里一律用**延迟取值**的箭头包装，调用时才去查外层变量：

```js
closeAll: (...a) => closeAll(...a),
```

这条经验对后面几刀都适用：**拆视图时 ctx 用箭头包装，不要直接传引用**（函数声明会
提升、`const` 不会）。`views/categories.js` 那几个 helper 恰好都是函数声明，所以第一刀
没撞上。

验收：`run_all` 8/8、`e2e` **90/90**；`app.js` 3744 → 3719 行。

**下一刀（P4.3-d）**：搬 `views/hall.js`（环/平铺布局 + `window.__aurora.ring()/layout()`
的取数逻辑，测试面签名不变）——这一块最大（环动画与拖拽都在里面），单独一轮做。

### P4.3-d 大厅视图第一刀：自检读出面 `views/hall.js`（2026-09-21 00:40）

大厅是最大的一块（环动画、拖拽、键盘导航、背景调度都在里面），所以拆两步走。
这一刀先搬**自检读出面**——`window.__aurora.ring()` / `layout()` 是 e2e / visual 的判据
来源，逻辑纯读、无副作用，最适合先独立：

| 改动 | 内容 |
| --- | --- |
| `gl/web/app/views/hall.js` | 新增 `ringReadout({RING, state})` 与 `layoutReadout({row, viewport, layoutName, flatClass})` |
| 设计选择 | 这两个函数**刻意不 import 任何东西**，依赖全部由调用方传入 —— 模块初始化阶段不存在 TDZ 风险（P4.3-c 的教训） |
| `gl/web/app.js` | `__aurora.ring/layout` 变成一行调用 + 传参；**返回结构一个字段都没动**，e2e/visual 判据不变；`app.js` 3719 → 3695 行 |

验收：`run_all` 8/8、`e2e` **90/90**。

**下一刀（P4.3-e）**：搬环本体（`RING` 配置与几何计算 → `views/hall.js`，动画/拖拽的写入方
留在主模块，通过 `ringHandle` 之类的接口交互），仍是每刀一跑 e2e/visual。

### P4.3-e 环几何进 `views/hall.js`（2026-09-21 01:10）

环本体第二步：把**几何**搬进 hall 模块，运行期状态与动画写入方仍留在主模块。

| 改动 | 内容 |
| --- | --- |
| `views/hall.js` 新增 | `RING_GEOMETRY`（step/rx/rz/depth/span/shrink/y/tau/dragPx 九个常量）、`RING_BASE`（180×270）、`ringGeometryOf({viewportWidth, viewportHeight, geometry, base, clamp})` —— 纯函数，视口尺寸与 clamp 都由调用方给 |
| `app.js` | `RING` 改成 `{ ...RING_GEOMETRY, items, nodes, keysSig, float, target, raf, last, ready, flatReady, dragActive }`（只留运行期字段）；`ringGeometry()` 变成三行调用（传 `RING` 而不是常量对象，语义与改前逐字一致） |

**为什么这样切**：几何是纯计算（可单测、无副作用），而动画/拖拽要在 60fps 里频繁写
`RING.float/target` 与 DOM 样式——两者混在一起反而是最难动的地方。先搬常量与几何，
下一刀再考虑把「帧循环」也搬过去（届时用 `createRing({...})` 之类接口交接）。

验收：`run_all` 8/8、`e2e` **90/90**、`visual` `errors=[]` 且 ring 判据（`ring_check`）仍在。

### P4.3-f 单张封面变换进 hall 模块（2026-09-21 01:40）

环本体第三步：把 `ringPlace(node, r)` —— 「第 r 格该是什么样式」这段纯映射 ——
搬成 `views/hall.js` 的 `placeRingTile(node, r, {ring, size})`，主模块里只留一行包装：

```js
const ringPlace = (node, r) => placeRingTile(node, r, { ring: RING, size: ringSize });
```

**验证方式（这一刀特意用数值比对）**：`visual.py` 的 `ring_check` 会读出每张封面在环上的
角度与投影位置。改动前后两次结果逐字相同（`["437e6a", 0, 347.0]`、`["db1d36", 16, 283.2]`
…），说明几何与明暗的数值一个都没变 —— 比只看「e2e 通过」更有说服力。

验收：`run_all` 8/8、`e2e` **90/90**、`visual` `errors=[]` 且 `ring_check` 数值不变。

**剩下的环本体（P4.3-g）**：帧循环（`ringFrame`/`ringRun`）、测量（`ringMeasure`）、
同步（`ringSync`/`clearRingStyles`）与拖拽/键盘。这几块要在 60fps 里频繁写 `RING.float/target`
与 DOM，建议用 `createRing({ el, ring, state, onFocus })` 交出 `{measure, sync, step, run, stop}`
的接口一次性搬完，仍以 `ring_check` + e2e 双验收。

### P4.3-g 环的叶子 helper 先归位（2026-09-21 02:05）

帧循环那一整块要一次搬完（`createRing` 接口，见上），但那之前先把**不涉及帧语义**的三个
叶子函数摘出来，主模块能少一点是一点：

| 搬到 `views/hall.js` | 说明 |
| --- | --- |
| `ringMod(i, n)` | 环上的循环取模（负数也落到 `[0, n)`） |
| `ringSigned(d, n)` | 折到 `[-n/2, n/2)`：第 i 项在第几圈、哪个方向 |
| `clearRingStyles(node)` | 清掉一张封面上的环样式（切平铺/重用节点时用） |

主模块里三处定义删掉、改成 import（调用点零改动，8 处引用照旧）。

验收：`run_all` 8/8、`e2e` **90/90**、`visual` `errors=[]` 且 ring 判据数值仍是
`0/347.0`、`16/283.2`（与前一刀逐字相同）。

**下一刀（P4.3-h）**：`createRing({ el, ring, state, onFocusChange, … })` 把
`ringMeasure`/`ringSync`/`ringFrame`/`ringRun` 与拖拽、键盘一起搬完；先存 `visual` 基线，
改完 `e2e` + `visual` 双验收并逐项比对 `ring_check`。

### P4.3-h 环的样式应用与键列表（2026-09-21 02:35）

帧循环整块（`createRing`）要一次搬完，这轮继续把其中**能安全摘离**的两处摘掉：

| 搬到 `views/hall.js` | 说明 |
| --- | --- |
| `applyRingSize({row, viewport, size})` | 把这一帧的环尺寸写到 `--gi-w` / `--gi-h` / `--ring-d` 三个样式变量（`ringSize` 这个运行期状态仍留主模块） |
| `hallKeysOf(visibleIds, addKey)` | 键列表 = 可见游戏 + 末尾「＋ 导入游戏」；可见游戏的筛选/排序仍由主模块决定 |

验收：`run_all` 8/8、`e2e` **90/90**、`visual` `errors=[]` 且 ring 判据数值
`0/347.0`、`16/283.2` 与前一刀逐字相同。

**P4.3-i（环的最后一刀）**：`createRing({ el, ring, state, onFocusChange, onKeys })` 一次性
搬完 `ringSync`/`ringFrame`/`ringRun`、`updateRowFlat` 与拖拽/键盘；仍以 `visual` 的
`ring_check` 数值 + `e2e` 双验收，偏差即回退。

### P4.3-i 平铺排布进 hall 模块（2026-09-21 03:05）

两种布局的**排布算法**现在都在 hall 模块里了：环是 `placeRingTile` + `ringGeometryOf`，
平铺是这次搬的 `updateFlatRow({row, viewport, keys, focus, ring, instant})`。

它把上下文全部显式传入（含运行期 `ring` 对象），并对齐 `ring.float/target` 到焦点索引
（这样切回环形布局时从这里接着转）；焦点不在列表里就返回 `false`，调用方不必再判。
主模块的 `updateRowFlat` 只剩一行调用。

验收：`run_all` 8/8、`e2e` **90/90**、`visual` `errors=[]` 且 ring 判据数值
`0/347.0`、`16/283.2` 不变。

**P4.3-j（环的最后一刀）**：`createRing({ el, ring, state, onFocusChange, onKeys })` 把
`ringSync`/`ringFrame`/`ringRun` 与拖拽/键盘一起搬完 —— 这一块要求在 60fps 里写
`ring.float/target` 与 DOM，改动面最大，必须一次做完并做 `e2e` + `visual` 双验收
（`ring_check` 数值逐项比对，偏差即回退）。目前环的**几何、单张变换、样式应用、键列表、
平铺排布**都已归位，这一刀只剩帧循环与输入处理。

### P4.3-j 环本体进 hall 模块（2026-09-21 11:00）

环的最后一刀：`views/hall.js` 新增 `createRing(ctx)`，把「谁在转这个环」整个收进去。

| 搬进 `createRing` | 说明 |
| --- | --- |
| `RING` 运行期对象 + `ringSize` | 位置 / 节点表 / 键签名 / 帧句柄改成模块内部持有（几何常量仍来自 P4.3-e） |
| `ringGeometry` / `ringMeasure` / `ringPlace` | 测量与逐张摆放；单张变换仍用 P4.3-f 的 `placeRingTile` |
| `ringSync` → `sync(keys)` | 节点复用、内容更新、顺序搬动；**返回列表是否变化**，主模块不再自己比对 `keysSig` |
| `ringFrame` / `ringRun` → `frame` / `run` | 60fps 帧循环与写入方 |
| `updateRow` → `update(instant)` | 两种布局的统一入口（平铺走 P4.3-i 的 `updateFlatRow`） |
| `applyHallLayout` → `applyLayout()` | 切布局时清另一套内联样式 + 直接就位 |
| `ringIndexOf` / `moveFocus` / `jumpFocus` → `move(delta)` / `jump(edge)` | 循环队列（平铺不循环）的规则一起搬走 |
| 悬停 / 单击 / 双击 / 横向拖动 / 滚轮 / `←→ Home End Enter` → `bind()` / `handleKey(e)` | 指针与键盘输入整块收口；`moved`（这次是拖还是点）与拖动同处一模块 |

主模块只剩三件事：`hallKeys()`（筛 / 排后的键列表）、`ringTileOf(key)`（每格的
html / 忙标记 / 标题）、以及 `enterGame` / `playGame` / `openAddMenu` 三个回调 ——
回调一律用箭头延迟取值包装（P4.3-c 的 TDZ 教训）。`setFocus` 里两处
`RING.dragActive` 改成 `ring.dragging()`；鼠标在窗口外松开 / 窗口切走时由
`ring.endDrag()` 补吸附；全局 keydown 只剩 `if (ring.handleKey(e)) return;`。

`window.__aurora.ring()/layout()` 返回结构一个字段没动（`ring.readout()` /
`ring.layoutName()`），e2e / visual 判据照旧。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90**（含滚轮、横向拖动、
拖动后单击仍进游戏页、双击直接启动等输入相关步骤）、`visual` `errors=[]` 且 ring 判据
`0/347.0`、`±16/283.2`、`32/232.5`、`focus_center_delta=0.0` 与改前逐项相同。
`app.js` 3618 → 3345 行，`views/hall.js` 198 → 578 行。

**下一刀（P4.3-k）**：视图清单里只剩 `views/game.js`（游戏页渲染与各处面板）——
大厅 / 分类 / 设置三块已归位，拆法沿用同一套：纯函数传参、回调用箭头延迟取值、
`window.__aurora` 与 e2e / visual 判据不变。

### P4.3-k 游戏页渲染面进 views/game.js（2026-09-21 11:15）

视图清单里只剩游戏页。这一刀先搬**渲染面**（纯读 + 拼 DOM），游戏页的各个面板
（背景 / 详情 / 匹配 / 资料源 / 转区 / 获取）留待下一刀 —— 与大厅当初
「先读出面、再几何、后本体」是同一个节奏。

| 搬到 | 内容 |
| --- | --- |
| `views/game.js`（新） | `createGameView(ctx)` 的 `renderGameContent`（LOGO / 标题 / 信息条 / 简介 / 运行状态 / 数据来源 / 加载遮罩），外加 `chip` / `descText` / `updateShowOriginalBtn` / `detailBody`（详情面板现在也 import 后两者） |
| `core/time.js`（新） | `hours` / `clock` / `sessionSeconds` / `stamp` —— 大厅信息带、游戏页信息条、详情面板、实时计时都要用，所以从主模块抽成共享块（调用点名字不变） |
| `core/dom.js` | 顺带收一个 `esc`：视图模块也要拼模板，`chip` 就靠它 |

`createGameView(ctx)` 只注入四样：`currentGame` / `syncBgZoomUi` / `startLiveTicker` /
`sourceName`，一律箭头延迟取值（P4.3-c 的教训）。主模块三处调用点改成
`gameView.renderGameContent()`；时长 / 时钟与 `detailBody` 变成 import，调用点一个字没动。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90**（含「界面显示简介 / 标签 /
LOGO / 背景图已应用 / 界面显示运行中」等游戏页判据）、`visual` `errors=[]` 且 ring 判据
与改前逐项相同。`app.js` 3345 → 3223 行。

**下一刀（P4.3-l）**：游戏页的**面板**——`renderDetail` / `renderBgPanel` +
`syncBgZoomUi` / `renderCoverPanel` / `renderMatches` + `openCandidates`，
每块单独一刀，仍以 `e2e`（详情 / 换封面 / 手动匹配 / 背景面板都有判据）+ `visual` 收口。

### P4.3-l 详情面板与背景面板进 views/game.js（2026-09-21 11:25）

游戏页的两块面板（含背景缩放）跟着渲染面一起归位：

| 搬到 | 内容 |
| --- | --- |
| `views/game.js` | `renderDetail`（信息表 / 游玩记录 / 截图墙）与 `renderBgPanel` + `syncBgZoomUi`（缩略图墙与缩放滑杆） |
| `core/dom.js` | 顺带收一个 `imgHtml`（带 `data-srcs` 备用链的 `<img>`，主模块与视图都要拼） |

主模块的调用点改走 `gameView.renderDetail()` / `gameView.renderBgPanel()` /
`gameView.syncBgZoomUi(g)`；分类视图的 `ctx.renderDetail` 也指到 `gameView`（箭头包装）。
事件绑定（`btnDetails` / `btnBackgrounds` / 截图墙点击 / `detailStatus` 改状态 / 缩放滑杆）
仍留在 `bindUi`，一个字没动。`createGameView(ctx)` 的注入项从五个减到四个：
`currentGame` / `startLiveTicker` / `sourceName` / `statusOrder+statusLabel`。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90**（详情面板改状态、切换背景、
背景缩放复位、获得多张背景候选全过）、`visual` `errors=[]`、ring 判据与 `zoom` 判据
（滑杆 180 → `scale(1.8)`、复位后 `transform=""`）与改前相同。`app.js` 3223 → 3120 行。

**下一刀（P4.3-m）**：换封面面板（`renderCoverPanel` + `coverCandidates`）与手动匹配
（`renderMatches` / `openCandidates` / `renderQuickQueries`）—— 这两块与后端调用耦合更紧，
每块单独一刀，仍以 `e2e`（更换封面 / 手动匹配 / 候选应用）+ `visual` 收口。

### P4.3-m 换封面面板与手动匹配进 views/game.js（2026-09-21 11:40）

游戏页面板里最后两块（都在「⋯」菜单后面）：

| 搬到 | 内容 |
| --- | --- |
| `views/game.js` | `renderCoverPanel` + `coverCandidates`（封面候选链）；`renderMatches` / `renderMatchLinks` / `renderQuickQueries` / `matchHintText` / `openCandidates`（手动匹配那套） |
| `views/game.js` | `sourceName`（资料源显示名）也一并归位 —— 它只被游戏页与候选列表用 |

面板的开合仍是主模块的事：`openCandidates` 里那一下 `openPanel(el.matchPanel)` 走
`ctx.openPanel(node)` 注入（`openPanel` / `closePanel` / `closeAll` 留到面板管路那一刀再搬）。
主模块保留的调用是 `openMatchPanel` / `doSearch` / `researchGame` / 封面三个按钮 / 事件推送里的
`metadata:notfound`，全部改成 `gameView.*`。

**这一刀踩到的坑（e2e 当场拦住）**：`sourceName` 搬进视图后，`renderGameContent` 里还有一处
`ctx.sourceName(...)` 没跟着改 —— 主模块已经不再注入这个回调，于是每次渲染游戏页都抛
`TypeError: ctx.sourceName is not a function`。因为 `renderGameContent` 在
`setFocus` → `render()` → `scheduleBackground()` 的链路上，症状看起来是「背景不应用、
方向键不动、设置和分类打不开」这种四处漏风的样子：e2e 第一次跑出 **27/46**。

定位方式：`_sandbox/p43m_probe.py` 真机开窗后挂 `window.onerror` 再点齿轮/封面，直接读到
`Uncaught TypeError: ctx.sourceName is not a function @app/views/game.js:130`。
改成模块内的 `sourceName(...)` 后 e2e 回到 **90/90**。
**教训**：搬函数时除了改调用点，还要把「被搬走的函数在别处被 `ctx.` 引用过」这种残留一起搜干净
（`rg 'ctx\.' views/*.js` 与 ctx 注入表对一遍）。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90**（更多菜单里的「更换封面…」、
「手动匹配…」、候选列表按匹配度排序、点候选才应用、重新搜索仍自动采纳全过）、
`visual` `errors=[]` 且 ring 判据不变。`app.js` 3120 → 2995 行，`views/game.js` 236 → 375 行。

**下一刀（P4.3-n）**：`app.js` 里剩下的两块 —— 面板管路（`openPanel`/`closePanel`/`closeAll`
与各面板的开关）与资料源管理 / Steam 扫描 / 获取游戏（`renderSources` / `renderSteamList` /
`renderSites` 这一组），之后 P4 只剩设置页内部的渲染。

### P4.3-n 资料源 / Steam / 获取游戏进 views/sources.js（2026-09-21 11:50）

这三个面板讲的是同一件事「游戏从哪来」，所以合成一个新模块 `views/sources.js`：

| 搬到 | 内容 |
| --- | --- |
| `views/sources.js`（新） | 资料源管理：`renderSources` / `refreshSources` / `applySourcesHint` / `syncSourceForm` / `addCustomSource` |
| 同上 | Steam 扫描导入：`openSteamPanel` / `renderSteamList` / `updateSteamHint` / `importSteam` |
| 同上 | 获取游戏：`openGetPanel` / `renderSites` / `refreshSites` / `openSite` / `addSite` / `refreshDownloadSettings` |

`createSourcesView(ctx)` 注入三样：`closeAll` / `openPanel` / `toast` —— 面板管路仍是主模块的
事（`openPanel`/`closePanel`/`closeAll` 这一刀没动）。主模块的调用点全部改成
`sourcesView.*`，其中 `bindUi` 里的 `.onclick = fn`（如 `$("steamImport").onclick`）
改成 `() => sourcesView.fn()`，保持箭头延迟取值的规矩。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90**（下载大厅面板打开且不溢出、
新增/删除资源站、下载目录设置已持久化全过）、`visual` `errors=[]` 且 ring 判据不变；
另外用 `_sandbox/p43m_probe.py` 真机确认：设置页可开、资料源面板渲染出 3 行、
获取游戏面板能开且无未捕获异常。`app.js` 2995 → 2800 行，`views/sources.js` 234 行。

**下一刀（P4.3-o）**：面板管路（`openPanel`/`closePanel`/`closeAll` 与各面板开关）——
它是 `views/game.js`、`views/settings.js`、`views/sources.js` 三边都要用的最后一块公共设施，
搬完就可以把「谁开哪个面板」也交给视图，`app.js` 只剩工具条与设置页内部渲染。

### P4.3-o 面板管路进 core/panels.js（2026-09-21 11:55）

面板的「开 / 关 / 全关」是三边都要用的公共设施，所以它不进任何视图，而是单独成 core 模块：

| 搬到 | 内容 |
| --- | --- |
| `core/panels.js`（新） | `openPanel` / `closePanel` / `closeAll`（9 个浮层 + 4 个工具条菜单），只做类名与菜单开关，不碰内容 |
| `views/game.js` | 新增 `openCoverPanel()`（全关 → 渲染候选 → 开面板）——「谁开哪个面板」跟着面板内容走 |
| `views/sources.js` | 新增 `openSourcePanel()`（全关 → 拉列表 → 开面板），`openSteamPanel` / `openGetPanel` 里的开合改成直接 import |

`createGameView` 的 ctx 从五项减到四项（去掉 `openPanel`），`createSourcesView` 的 ctx 从三项减到一项
（只剩 `toast`），`createSettingsView` 去掉 `closeAll`（`openSettings` 里改成 import）。
主模块保留 `closePanel(el.…面板)` 这类一行关闭按钮的绑定（它们本来就在 `bindUi`）。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90**、`visual` `errors=[]` 且 ring 判据不变；
真机探针另外确认：设置页可开、资料源面板 3 行、获取游戏面板可开、
**更多菜单 → 更换封面… 打开面板并渲染出 24 个候选**（e2e 没直接覆盖这一条，靠探针补上），
全程 `__auroraErrors=[]`、无未捕获异常。`app.js` 2800 → 2774 行。

**下一刀（P4.3-p）**：游戏内翻译面板那一组（`renderVntextPanel` / `renderVntextSettings` /
`refreshVntext` / `renderGlossary` / `setGlossary` / `openVntextPanel` / `openFraming` /
`bindVntext`，约 250 行）—— 它是 `app.js` 里剩下最大的一块，玩法照旧：渲染进视图、
后端调用留在视图、事件绑定按需一起搬。

### P4.3-p 游戏内翻译整块进 views/vntext.js（2026-09-21 12:05）

`app.js` 里剩下的最大一块（约 420 行）整块搬走，包括它的**事件绑定**：

| 搬到 | 内容 |
| --- | --- |
| `views/vntext.js`（新） | `renderVntextPanel` / `renderVntextSettings`（面板 + 设置页那一栏）、`VN_ERROR_LABEL` + `vnErrorText`（错误码人话化）、`refresh` |
| 同上 | 术语表：`renderGlossary` / `setGlossary` |
| 同上 | OCR 框选：`openVntextPanel` / `openFraming` / `bindFraming`（截图 → 拖框 → 存归一化区域） |
| 同上 | 钩子查找器与全部按钮绑定：`bind()`（含 `PHASE_LABEL`、轮询计时器、候选点击、线程锁定、引擎/字体/透明度等设置项） |
| `core/store.js` | 顺带把 `ADD_KEY`（「＋ 导入游戏」占位键）从主模块搬出来 —— 视图也要用它判断「当前不是游戏」 |

视图对外只留五个口子：`bind()` / `refresh()` / `renderGlossary()` /
`renderPanel(status)` / `onHookSearch(payload)`；主模块的推送事件（`vntext:status` /
`hooksearch:status` / `vntext:line`）与设置页 ctx（`refreshVntext` / `renderGlossary`）都改走它们。
查找器的轮询计时器与「一直没抓到文本」的计时器现在是视图内的私有状态（以前挂在主模块顶层）。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90**（设置页「游戏内翻译」页签与 TextractorCLI 识别、
钩子模式开启、假钩子日文翻成中文并进面板、面板状态与线程、专用 hook 码存取、乱填被拒、停止翻译收起悬浮窗
—— 这一组全过）、`visual` `errors=[]` 且 ring 判据不变；真机探针另外确认面板打开后
`vnState` = 「未开启 · 已译 0 句」、OCR 说明与 hook 说明都渲染出来。
`app.js` 2774 → **2366 行**，`views/vntext.js` 452 行。

**下一刀（P4.3-q）**：`app.js` 剩下的主要是控制层了 —— 窗口/背景绑定、工具条（搜索/排序/作用域）、
推送事件分发与 `boot()`。可以先把「工具条 + 作用域」拆成 `views/toolbar.js`，
再看推送分发要不要单独成 `core/events.js`。

### P4.3-q 筛选 / 排序 / 作用域进 core/query.js + 工具条进 views/toolbar.js（2026-09-21 12:50）

工具条这一刀把「查询」和「界面」分开：

| 搬到 | 内容 |
| --- | --- |
| `core/query.js`（新） | `searchHit` / `sortGames` / `inScope` / `scopeName` / `scopeCount` / `visibleGames`，以及 `STATUS_LABEL` / `STATUS_GLYPH` / `STATUS_ORDER` 三张表 —— 全是纯读，主页与分类工作区共用同一份，「两处结果永远一致」只在一个地方维持 |
| `views/toolbar.js`（新） | 作用域胶囊（文案 + 清除按钮）、作用域菜单（范围 / 自定义分类 / 按状态 / 按开发商 + 定位）、`setScope`（含焦点修正与重绘）、排序菜单（选中态 + 右对齐定位 + 开合） |

`createToolbarView(ctx)` 只注入两样：`render` 与 `ringUpdate`（改作用域后重绘 + 让环就位）。
主模块的 `bindUi` 里，`$("scopePick")` / `$("btnSort")` 变成 `toolbar.toggleScopeMenu()` /
`toolbar.toggleSortMenu()`，其余作用域与排序的调用点改走 `toolbar.*`；查询函数变成 import，
调用点一个字没动。

**这一刀踩到的坑（又是 e2e 当场拦住）**：主模块的 `catList()` 还在用 `inScope`，
但它已经搬去 `core/query.js`，而 import 列表里漏了它 —— 于是**分类界面打不开墙**
（`cards: 0`），e2e 第一次跑出 34/43。补上 import 后恢复 90/90。
教训同 P4.3-m：搬函数时要把「被搬走的函数在主模块还有哪些调用点」逐个对一遍 import 清单。
（这次两轮 e2e 还夹着一次网络抖动：Steam 取不到详情时那 6 项会被判跳过，等网络恢复重跑即
`90/90, 0 skipped`；顺手给探针补了「切到分类界面」这一步，正是它没被覆盖才漏过 `inScope`。）

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90（0 skipped）**——
「主页按分类过滤 + 作用域胶囊」「主页能直接选分类（作用域菜单）」「「已收藏」能当分类用」
「作用域胶囊能清除筛选」全过；`visual` `errors=[]` 且 ring 判据不变；
真机探针确认作用域菜单 7 行、选中「已收藏」后胶囊变 `已收藏 · 0`、清除后回 `全部游戏 · 0`、
排序菜单可开、分类界面无未捕获异常。`app.js` 2366 → 2233 行。

**下一刀（P4.3-r）**：`app.js` 只剩控制层了 —— 窗口/背景绑定、推送事件分发（14 个主题）、
`boot()` 与设置页里的剩余绑定。建议先拆推送分发 → `core/events.js`（每个主题一段处理，
主模块只留 `__aurora.emit` 的入口与 `render()` 调用），再收窗口/背景。

### P4.3-r 推送事件分发进 core/events.js（2026-09-21 12:55）

后端 14 个主题的那条 if/else 长链搬成一张处理表：

| 搬到 | 内容 |
| --- | --- |
| `core/events.js`（新） | `createEventRouter(ctx)`：`game:updated/stopped/running`（合一个实体状态处理）、`metadata:searching/notfound/error`、`games:imported`、`batch:progress/done`、`translate:done`、`vntext:status`、`hooksearch:status`、`vntext:line`、`downloads:status` |
| 同上 | `notifyLocaleStart`（转区启动提示）与 `hintCoverOnce`（没抓到封面只提醒一次）跟着搬进事件层 —— 它们本来就只被事件用 |

`ctx` 注入渲染与各视图口子（`render` / `renderHall` / `refreshLibrary` / `setFocus` /
`scheduleBackground` / `currentGame` / store 的实体更新 helper / `toast` /
`gameView.openCandidates` / `sourcesView.updateSteamHint` / `vntext.{renderPanel,onHookSearch,renderGlossary,refresh}`），
主模块的 `__aurora.emit` 变成一行：`emit: (event, payload) => events.emit(event, payload)`。
未知主题直接忽略；单个主题抛错只记 console（与拆分前一致）。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90（0 skipped）**、`visual` `errors=[]`
且 ring 判据不变；真机探针这一刀加了**直接推事件**的检查 —— 合成一条 `games:imported`
（含 1 个假游戏）后：大厅多出一格、提示冒泡到 toast「已导入 1 个游戏」、分类墙也跟着出现该游戏、
再推一个不存在的主题不抛错。`app.js` 2233 → 2121 行，`core/events.js` 190 行。

**下一刀（P4.3-s）**：只剩窗口 / 背景绑定与 `boot()` 了 —— 可以把窗口控制（拖拽、缩放、
最小化/最大化）与背景层（双缓冲、淡入、图片回退链）各拆一个模块，之后 P4 就只剩「打包清单
与文档同步」这一项收尾。

### P4.3-s 窗口外壳与背景层（2026-09-21 13:05）

主模块里最后两块「非业务」的界面逻辑各自成模块：

| 搬到 | 内容 |
| --- | --- |
| `core/window.js`（新） | 无边框窗口的拖拽 / 四边缩放 / 最小化 · 最大化 · 关闭按钮 / 双击标题栏最大化 / 「鼠标在窗口外松开」的状态清理。`drag`、`resize` 两个指针状态变成模块内部私有；大厅的划封面拖动由 `ctx.onPointerReset`（主模块传 `() => ring.endDrag()`）通知 |
| `views/background.js`（新） | 双缓冲背景层（`bgSide` / `bgCurrent` 私有）、`applyBackground`（预加载成功再淡入、渐变直接切）、`fallbackBackground` + `hashHue` + `DEFAULT_BACKGROUND`、`scheduleBackground`（延迟淡入 + 预取左右邻居）、`updateBgView`（缩放 + 350ms 防抖持久化）、`chooseBackground` / `pickLocalBackground`、背景面板的按钮与缩放滑杆，以及全局图片回退链（`data-srcs`） |

`ctx` 注入：`currentGame` / `hallKeys` / `syncBgZoomUi` / `renderBgPanel` / `toast`。
设置页改 Ken Burns 那一处改走 `background.applyKenBurns(value)`；`cssUrl` 只剩背景层用，
跟着搬进 `views/background.js`（主模块删掉）。`boot()` 的绑定循环改成
`[["窗口", () => bindWindowControls({ onPointerReset: () => ring.endDrag() })], ["背景", () => background.bind()], ["界面", bindUi]]`。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90（0 skipped）**——
窗口那组（拖拽移动窗口、拖拽缩放窗口、最小尺寸被钳制、最大化窗口、还原窗口）与背景那组
（背景图已应用、切换背景生效、缩放滑杆生效、背景缩放复位）全过；`visual` `errors=[]`、
ring 判据与 `zoom` 判据（滑杆 180 → `scale(1.8)`）不变；探针跑完全部界面无未捕获异常。
`app.js` 2121 → **1862 行**，`core/window.js` 92 行、`views/background.js` 227 行。

**下一刀（P4.3-t）**：`app.js` 只剩「拼装 + 业务动作」了 —— `boot()`、`bindUi` 里剩下的
设置页 / 详情 / 匹配面板绑定、`refreshLibrary` / `importGames` / `togglePlay` / 匹配流程。
建议先把设置页那一大组绑定（主题、资料源、转区、网络、备份）搬进 `views/settings.js` 的
`bind()`，再把「游戏动作」（启动 / 结束 / 导入 / 批量）收进 `views/game.js` 或新的
`core/actions.js`，之后 P4 只剩打包清单与文档同步收尾。

### P4.3-t 设置页整块收口（2026-09-21 13:10）

P4.3-c 只搬了设置页的页签导航，这次把**整页**都收进 `views/settings.js`：

| 搬到 | 内容 |
| --- | --- |
| `views/settings.js` | 主题与配色：`PALETTES` / `lightQuery` / `effectiveTheme` / `applyTheme` / `renderPaletteRow`，以及 `bindTheme` 的内容（主题、主页布局、配色、跟随系统） |
| 同上 | 设置页各栏：网络（`refreshNetworkPane` / `renderNetResults` / `testNetwork`）、转区（`refreshLocalePane`）、`LE_URL` |
| 同上 | 外观回填与落盘：`applySettingsToUi`（含 `--blur`/`--sat`/`--scrim`/`--accent` 与各控件回填）、`saveSetting`（写 state → 回填 → Ken Burns 生效 → 落盘） |
| 同上 | `bind()`：页签 / 网络 / 转区 / 外观滑杆 / 简介翻译（含接口测试）/ 显示原文 / 资料源与 Steam / 批量重抓与翻译 / 备份导出与导入 |

主模块只留**单个游戏的转区面板**（`renderLocalePanel` / `openLocalePanel` / `saveGameLocale`
与那几个按钮）—— 它属于游戏页那边的面板，下一刀跟着走。`LE_URL` 由设置视图导出，
两处共用一份。`ctx` 注入变成：`render` / `toast` / `ringApplyLayout` / `applyKenBurns` /
`openSourcePanel` / `openSteamPanel` / `startRefreshAll` / `startTranslateAll` /
`refreshLibrary` / `refreshVntext` / `renderGlossary`；`refreshLibrary` 里的回填改走
`settingsView.applySettingsToUi()`。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90（0 skipped）**——设置页那组全过
（能打开且盖住大厅、切到网络页读到代理状态、网络测试列出五个端点、切到转区页、切到翻译页识别
TextractorCLI、浅色主题生效、配色预设切换、切回深色+默认配色、设置页里滚轮/方向键不串台、
最小窗口下不溢出、返回按钮退出）；`visual` `errors=[]` 且 ring 判据不变；探针跑完各界面
（含设置页打开后的渲染）无未捕获异常。`app.js` 1862 → **1571 行**，`views/settings.js` 54 → 379 行。

**下一刀（P4.3-u）**：`app.js` 只剩「游戏动作 + 拼装」了 —— `importGames` / `refreshLibrary` /
`togglePlay` / `startRefreshAll` / `startTranslateAll` / 单个游戏的转区面板 / 匹配流程
（`openMatchPanel` / `doSearch` / `researchGame` / `applyCandidate`）/ 更多菜单的绑定，
以及 `boot()` 与全局快捷键。建议把「游戏动作」收进 `core/actions.js`、转区面板与匹配流程
收进 `views/game.js`，最后一刀只剩 `boot()`。

### P4.3-u 游戏动作进 core/actions.js、匹配与转区面板进 views/game.js（2026-09-21 16:40）

| 搬到 | 内容 |
| --- | --- |
| `core/actions.js`（新） | `importGames`（选 exe → 刷新 → 聚焦 → 回大厅）、`refreshLibrary`（bootstrap 是唯一来源）、`togglePlay`（启动失败的两类人话提示）、`startRefreshAll` / `startTranslateAll`（先占位再收事件）、`startLiveTicker`（只改 `#chipLive`，不整页重绘） |
| `views/game.js` | 手动匹配流程：`openMatchPanel` / `doSearch` / `researchGame` / `applyCandidate`；单个游戏的转区面板：`renderLocalePanel` / `openLocalePanel` / `saveGameLocale`（转区面板从「设置页那一栏」分出来，归到游戏页这边） |

`createActions(ctx)` 注入 `render` / `setFocus` / `closeGame` / `toast` / `currentGame` /
`applySettingsToUi` / `renderSources` / `applySourcesHint` / `refreshShelves`；
`createGameView(ctx)` 的注入项加上 `render` 与 `toast`。主模块的调用点全部改走
`actions.*` / `gameView.*`，顺手删掉不再用的 import（`replaceGames`、`clock`、`sessionSeconds`）。

**这一刀踩到的坑（e2e + 探针一起抓到的）**：`views/game.js` 原本不需要 `call`（P4.3-k 只搬渲染），
这次搬进去的匹配与转区流程要调后端，但 **import 列表里漏了 `call`** —— 于是
「转区开关写进游戏记录」和「手动搜索只列候选」两项静默失败（`Uncaught (in promise) TypeError: call is not defined`），
e2e 第一次跑出 61/64/65 三项失败。因为它是 async 函数里的报错，`window.onerror` 抓不到，
最后靠探针里的 `unhandledrejection` 监听读出来（`_sandbox/p43u_locale_probe.py`）。
补上 `import { call } from "../core/api.js";` 后，同一条链路回读 `locale_enabled=True`、e2e 回到 90/90。
教训：往视图里搬**会调后端**的函数时，先把该视图的 import 清单与依赖对一遍；e2e 的报错可能是
「静默 + 连带」，探针要同时挂 `error` 与 `unhandledrejection`。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90（0 skipped）**——转区面板与开关写入、
手动匹配候选列表（10 条、按匹配度排序、点候选才应用）、双击封面启动、启动/结束进程全过；
`visual` `errors=[]` 且 ring 判据不变。`app.js` 1571 → **1355 行**，`core/actions.js` 113 行、
`views/game.js` 383 → 526 行。

**下一刀（P4.3-v，P4 收尾候选）**：`app.js` 里剩下的基本是「分类工作区渲染 + 更多菜单/分类绑定
+ boot()」。可以先把分类工作区那一组（`DEV_LIMIT` / `catList` / `catItem` / `renderCatRoots`…
`renderCategories` / `applyShelfPayload` / `refreshShelves`，约 180 行）搬进 `views/categories.js`，
再把 `bindUi` 里分类与更多菜单的绑定交给各自的 `bind()`，最后 `app.js` 只剩 `boot()` 与拼装。

### P4.3-v 分类工作区整块收口（2026-09-21 16:50）

`views/categories.js` 从「只有动作」变成「整屏都在这里」（118 → 415 行）：

| 搬进 / 合并 | 内容 |
| --- | --- |
| 渲染 | `DEV_LIMIT` / `catList` / `catItem` / `renderCatRoots` / `renderCatShelves` / `renderCatStatus` / `renderCatDevs` / `renderCatHead` / `renderCatWall` / `renderCatBar` / `renderCategories` |
| 数据收尾 | `applyShelfPayload`（货架 + 受影响游戏 + 解绑）与 `refreshShelves` |
| 绑定 | `bind()`：`categoriesView` 的事件委托（范围 / 开发商更多 / 分类上移下移重命名删除 / 批量条 / 卡片）、`catNew` / `catCancel` / `catCreate` 提交、以及分类屏与主页共用的搜索 / 排序同步 |
| 视图 ctx | `render` / `renderHall` / `setScope` / `syncSortMenu` / `renderDetail` / `setFocus` / `openPanel` / `coverSources` / `toast` / `modal` / `cssEscape`（`STATUS_LABEL` 改为视图内 import `core/query.js`） |

**顺手修掉一个潜伏 bug**：分类左栏的 ↑ / ↓ 按钮绑的是 `moveShelf(...)`，但**这个函数从来没定义过** ——
点一下就是 `ReferenceError: moveShelf is not defined`（e2e 没覆盖分类排序，所以一直没暴露）。
这次按后端既有契约 `move_shelf(shelf_id, delta)` 补上实现（`applyShelfPayload` 收尾），
并把 `move_shelf` 作为前端调用点补登进契约快照（96 → 97）。

**工具也跟着修**：`tools/checks/update_contract.py` 之前只扫 `gl/web/app.js`（P4.3-a 之前的口径），
搬进视图的调用点它看不见，于是快照更新是空的、`check_contract` 却报「新增调用」。
现在它与 `check_contract` 同口径扫 `app.js + gl/web/app/**`。

验收：`run_all` 8/8（契约：前端调用点 97 个全部有后端实现）、`pytest` 51 passed、
`e2e` **90/90（0 skipped）**——分类那条链全过（打开分类界面、新建分类并自动切过去、
整理模式勾选、多选归类写库、批量收藏、主页按分类过滤、作用域菜单、已收藏当分类、清除筛选、
重命名、删除只解绑）；`visual` `errors=[]` 且 ring 判据不变；探针确认分类屏渲染正常。
`app.js` 1355 → **1093 行**，`views/categories.js` 118 → 415 行。

**下一刀（P4.3-w，P4 收尾）**：`app.js` 只剩「更多菜单绑定 + 全局快捷键 + boot() + 拼装」。
建议把更多菜单与匹配/详情那几组绑定搬进 `views/game.js` 的 `bind()`，之后 `app.js`
就只剩工厂装配、`__aurora` 测试面与 `boot()` —— P4 的「拆视图」部分即可收口。

### P4.3-w 事件绑定交还给视图（2026-09-21 17:00）

最后一刀把 `bindUi` 里剩下的绑定按归属分给三个视图，主模块只留全局外壳：

| 搬到 | 内容 |
| --- | --- |
| `views/game.js`（+ `bind()`） | 详情面板（`btnDetails` / `detailClose` / 截图设为背景 / `detailStatus` 改状态）、候选匹配面板（`matchClose` / `matchGo` / 回车 / 候选点击 / 快捷词 / 跳转源搜索 / `matchRetry`）、更多菜单（`btnMore` 的可见项与文案 + 14 个动作：收藏 · 重命名 · 恢复命名 · 换封面 · 换图标 · 打开来源 · 重新搜索 · 手动匹配 · 转区 · 翻译简介 · 启动参数 · 移除）、转区面板（开关 / 配置 / 指定 LEProc / 下载页）、换封面面板（选图 / 本地图 / 恢复默认） |
| `views/sources.js`（+ `bind()`） | Steam 面板（关闭 / 全选 / 清空 / 导入 / 勾选联动）、获取游戏面板（关闭 / 改目录 / 打开目录 / 监听 / 解压 / 扫描 / 站点增删与搜索跳转）、末尾方块的二选一菜单、资料源管理（关闭 / 新增表单 / 来源上下移 / 测试 / 删除 / 启停开关） |
| `views/toolbar.js`（+ `bind()`） | 视图切换（主页 ↔ 分类）、作用域胶囊与菜单、搜索框（输入 / 清除 / 回车进第一项）、排序菜单 |

`ctx` 相应补齐：`gameView` 加 `modal` / `chooseBackground` / `setGameStatus` / `refreshLibrary` /
`closeGame` / `leUrl`；`sourcesView` 加 `importGames` / `refreshLibrary` / `render`；
`toolbar` 加 `renderHall` / `setView` / `refreshShelves` / `setFocus` / `openGame` / `currentGame` / `toast`。
主模块的 `bindUi` 现在只剩：顶栏三个按钮、「窗口尺寸变化后重新摆位」的两个观察器、
六行 `xxxView.bind()`，以及全局的 click-outside / 快捷键 / 右键 / 拖放提示。

**探针又立功一次**：新绑定里用了 `closePanel`，但 `views/game.js` 与 `views/sources.js` 的
import 列表里只有 `closeAll, openPanel`（以前它们不开面板，用不到 `closePanel`）—— 三处
`ReferenceError: closePanel is not defined`（点关闭按钮时）。因为这次是同步点击处理器，
`window.onerror` 一次抓齐，补 import 后探针 `errors=[]`。

验收：`run_all` 8/8、`pytest` 51 passed、`e2e` **90/90（0 skipped）**、
`visual` `errors=[]` 且 ring 判据不变；探针跑完全部界面（设置 / 资料源 / 获取 /
换封面 24 个候选 / 翻译面板 / 工具条 / 分类屏 / 事件推送）无未捕获异常。
`app.js` 1093 → **746 行**；`views/game.js` 526 → 730、`views/sources.js` 243 → 376、
`views/toolbar.js` 118 → 178。

**P4 拆视图到此收口**：`app.js` 只剩工厂装配、`__aurora` 测试面、`boot()` 与全局外壳，
15 个模块各司其职。下一步可选：把 `bindUi` 里最后的全局快捷键/拖放提示也整理成
`core/shell.js`（纯搬家，无行为变化），或转到路线图的下一项（打包清单与文档同步收尾）。

### P4.3-x 全局外壳与打包清单守卫（P4 收尾，2026-09-21 17:15）

两件收尾活一起做：

| 事项 | 做法 |
| --- | --- |
| `core/shell.js`（新） | 全局外壳搬出主模块：点空白收起工具条菜单、`Esc` 逐层退出（面板 → 设置 → 分类 → 游戏页）、拦 `F5`/`Ctrl+R`、`Ctrl+F` 聚焦搜索、其余按键交给大厅（`handleRingKey`）、右键菜单策略、拖放提示层。ctx 只有四项：`closeSettings` / `setView` / `closeGame` / `handleRingKey` |
| `tools/checks/check_packaging.py`（新） | **打包清单单一来源的可执行守卫**：用 AST 读 `build_exe.py` 里的 `WEB_FILES` / `WEB_MODULE_DIRS` / `WEB_USER_DIRS`，与 `gl/web` 实际目录对照 —— 清单里写的必须存在；`gl/web` 顶层**不允许有未登记条目**（漏登记 = 打包后页面 404） |
| `run_all.py` | 新检查挂进清单（第 9 项），跑一次即报「4 个顶层文件 + 1 棵模块树（22 个文件）、3 个用户素材目录不进包」 |

守卫的自我验证：往 `gl/web` 放一个未登记的 `stray-probe.js`，`run_all` 立刻变红
（`gl/web 下有没写进打包清单的文件：stray-probe.js`），删掉即恢复 9/9 —— 满足路线图
「故意违规能让 CI 变红」的要求。

验收：`run_all` **9/9**、`pytest` 51 passed、`e2e` **90/90（0 skipped）**、
`visual` `errors=[]` 且 ring 判据不变；`Aurora.exe` 用 `tools/build_exe.py` 重新打包
（本地产物，`.gitignore` 排除）以便真机直接体验新前端。`app.js` 746 → **692 行**。

### P4 阶段收口小结（2026-09-21）

| 维度 | 起点（P4.0） | 终点（P4.3-x） |
| --- | --- | --- |
| `gl/web/app.js` | 3688 行 IIFE | **692 行**（工厂装配 + `boot()` + `__aurora`） |
| 前端模块 | 0 | 16 个：`core/{api,actions,dom,events,panels,query,shell,store,time,window}.js` + `views/{background,categories,game,hall,settings,sources,toolbar,vntext}.js` |
| 状态与桥接 | 全局散落 | `core/store.js` 单一状态、`core/api.js` 唯一桥接出口、`core/events.js` 14 主题分发 |
| 打包清单 | `build_exe.py` 硬编码 4 个文件 | 清单仍是那 4 个文件 + `app/` 模块树，但**有守卫保证不漏**（`check_packaging`） |
| 离线检查 | 8 项 | **9 项**（新增打包清单检查） |
| 真机判据 | — | `e2e` 90/90（0 skipped）、`visual` errors=[] 且 ring 判据自 P4.3-d 起逐项未变 |

迁移期共抓到 4 类真实回归（都靠 e2e / 探针拦下并当轮修掉，记录在各自小节）：
`ctx.sourceName` 残留（P4.3-m）、漏 import `inScope`（P4.3-q）、漏 import `call`（P4.3-u）、
漏 import `closePanel`（P4.3-w），以及一个**本来就不存在**的 `moveShelf`（P4.3-v 顺手补齐）。

## P5 资产服务化（2026-09-21 17:30）

ADR-0005 的落地：用户素材只留一份（`data/{backgrounds,covers,icons}`），由自建静态服务按
`/assets/…` 暴露，彻底删掉「复制到 web 目录」这条链路。

| 改动 | 内容 |
| --- | --- |
| `aurora/infra/webserver.py`（新） | `ThreadingHTTPServer` 绑 `127.0.0.1:0`（系统挑空闲端口），后台守护线程 `aurora-webserver`；`/` 服务随包前端（`no-store`），`/assets/<mount>/<file>` 映射数据目录（`no-cache`）；只允许 `GET` / `HEAD`（其余 405 + `Allow`），`..` / 编码穿越 / 绝对路径 / 未挂载目录名一律 403/404 |
| `aurora/infra/config.py` | 删 `USER_BG_DIR` / `USER_ICON_DIR` / `USER_COVER_DIR` 与 `sync_user_assets()`；新增 `ASSET_MOUNTS`（挂载表），`ensure_dirs` 改回只建数据目录 |
| `main.py` | 启动时起服务并把入口指向 `http://127.0.0.1:<port>/index.html?v=…`；窗口关闭时 `server.stop()`；`build_window()` 未传 server 时自己起一个（探针因此也走真实路径） |
| 素材 URL | 后端产出的路径统一为 `assets/{backgrounds,covers,icons}/…`（桥接层 3 处 + OCR 截图 1 处）；`apply_window_icon` 改从 `ICON_SOURCE_DIR` 取原图 |
| 老数据兼容 | `aurora/app/projection.py` 在投影给前端时把 `userbg/…` / `usercovers/…` / `usericon/…` 改写成 `assets/…`（不动磁盘上的库文件） |
| 打包 | `tools/build_exe.py` 删掉 `WEB_USER_DIRS` 与「只留目录」的占位；`check_packaging` 兼容两种形态（现在报「用户素材不在 web 目录」） |
| 其它 | `.gitignore` 去掉三条副本目录规则；`gl/web/{userbg,usercovers,usericon}` 实体目录已删除 |

**验收（刻意用探针而不是肉眼看）**：

| 探针 | 结果 |
| --- | --- |
| `_sandbox/p5_assets_probe.py`（无窗口） | **15/15**：首页 / 入口模块 / 模块树 / 根路径回落可读；`/assets/` 素材 200 且字节一致、HEAD 支持；`../`、`%2e%2e`、出 web 根、绝对路径四类穿越被拒；未挂载目录名 403；目录本身 404；`POST` 405；老 URL 投影改写正确、新 URL 原样 |
| `_sandbox/p5_asset_window_probe.py`（真窗口） | 背景层读到 `url("http://127.0.0.1:…/assets/backgrounds/…")`（新老 URL 都一样）；页面内 XHR 取该图 **200 / `image/png` / 183 字节 / `no-cache`** |
| `tools/e2e.py` | **90/90（0 skipped）** —— 窗口现在就是从这个自建服务加载的 |
| `tools/visual.py` | `errors=[]`，ring 判据与改前逐项相同 |
| `tools/checks/run_all.py` | **9/9**（打包清单检查同步放宽；`aurora-webserver` 线程已登记进基线） |

**没验到的**：本机只有 Edge WebView2，Qt 内核（备选）没装，所以「双内核」只实测了 WebView2 那一半；
页面走的是标准 `http://127.0.0.1`，Qt 侧理论上等价，等有环境再补测（ADR-0005 的回退开关仍保留选项 1 的思路）。

