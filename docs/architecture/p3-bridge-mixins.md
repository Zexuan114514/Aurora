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

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 继承让「方法在哪」变模糊 | 读 `gl/api.py` 看不到全部方法 | 契约快照 + `update_contract.py --write` 的输出会列全量方法；mixin 头部写明范围 |
| mixin 之间互相调用 | 搬第二刀时可能出现跨 mixin 调用 | 允许（同一个 `self`），但禁止跨 mixin 访问对方的私有属性；需要共享状态时上移到 `Api.__init__` |
| 临时 `gl` 依赖 | 桥接层仍 import 遗留模块 | 已在 `check_layers` 里显式列出，P3.2 归零 |
