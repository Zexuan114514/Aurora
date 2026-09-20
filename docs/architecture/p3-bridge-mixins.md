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

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 继承让「方法在哪」变模糊 | 读 `gl/api.py` 看不到全部方法 | 契约快照 + `update_contract.py --write` 的输出会列全量方法；mixin 头部写明范围 |
| mixin 之间互相调用 | 搬第二刀时可能出现跨 mixin 调用 | 允许（同一个 `self`），但禁止跨 mixin 访问对方的私有属性；需要共享状态时上移到 `Api.__init__` |
| 临时 `gl` 依赖 | 桥接层仍 import 遗留模块 | 已在 `check_layers` 里显式列出，P3.2 归零 |
