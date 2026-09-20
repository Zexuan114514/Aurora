# 01 架构选项（architecture-option-generator）

## Summary

给 Aurora 找出 4 个**可信**的结构选项，并按「单人维护 + 社区贡献 + 零新增运行时依赖 + 单文件 exe」
这四个驱动去比较。推荐 **选项 A：模块化单体 + 端口适配**；其余选项不是坏方案，而是在当前约束下
代价明显更高。

## Context

- **问题**：项目能跑、功能完整、真机验证充分，但结构上没有边界：`gl/api.py` 既是对外契约又是业务编排，
  `gl/vntext.py` 把纯文本规则、引擎表、子进程协议、OCR 循环混在一起，前端是一个 3688 行的 IIFE，
  数据是一个每次改动都全量重写的 JSON。
- **范围**：`main.py` + `gl/`（24 个模块）+ `gl/web/`（前端）+ `tools/`（探针与打包）。
- **约束**：Windows-only；pywebview 只暴露顶层方法；外部工具不可打包；运行时依赖零新增；单文件 exe 免安装；
  两个 `.bat` 的 GBK + CRLF 编码不可变。
- **不做**：跨平台、多用户、云端账号、安装器、Web 前端框架化。

## 选项

### 选项 A：模块化单体 + 端口适配（推荐）

- **Shape**：仍是单进程单 exe。包内分 `domain`（纯规则）/ `app`（用例 + 端口 Protocol）/ `infra`（适配器）/
  `platform`（ctypes 原语）/ `ui`（桥接 mixins + 窗口 + 前端静态资源），`bootstrap.py` 作为唯一组合根。
- **Strengths**：不动运行形态，风险最低；纯规则（文本清洗、匹配打分、会话结算、引擎规则）可离线单测，
  这是当前最缺的能力；插件与规则包有天然落点；桥接方法名可以逐个搬迁并保持兼容。
- **Weaknesses**：Python 没有编译期边界，靠 AST 守卫与评审约束；迁移期间 `gl` 与新包并存（需要转发 shim）。
- **Best fit when**：单人维护、要长期演进、要接受社区 PR，但不想增加发布与调试复杂度 —— 正是当前处境。

### 选项 B：按技术分层的分层单体（不引入端口）

- **Shape**：只分 `ui / service / data / utils` 四层，模块之间直接互相 import 具体实现。
- **Strengths**：改造量最小，`api.py` 拆成几个 service 就算完成；上手快。
- **Weaknesses**：测试仍要碰真实 Win32/HTTP/子进程；换存储、换翻译引擎、换文本源都要改调用方；
  「加一个资料源」这种社区场景依旧要动核心文件。
- **Best fit when**：项目已冻结、只做维护性修复，不需要扩展点。

### 选项 C：模块化单体 + 关键子系统进程隔离

- **Shape**：主进程保留 UI 与库，`vntext`（钩子 + OCR + 内存扫描）与翻译各自跑在子进程，用本地管道通信。
- **Strengths**：调试器/内存扫描这类高风险代码崩了不拖垮主进程；可单独重启文本链路。
- **Weaknesses**：pywebview 已经是「主进程 + 渲染进程」模型，再加多层子进程会让打包、日志、生命周期、
  真机排错（TextractorCLI 本身也是子进程）复杂度陡增；零依赖下 IPC 要自研；对单人维护是负担。
- **Best fit when**：实测出现「钩子/扫描导致主进程崩溃」的高频现象；当前 `hookfinder` 只在用户手动触发时运行。

### 选项 D：桌面壳 + 常驻本地后台服务

- **Shape**：pywebview 只做壳，能力放进本地 HTTP/管道服务（可用 FastAPI 之类），支持多窗口与后台常驻。
- **Strengths**：未来若要多窗口、后台常驻、外部程序集成，扩展性最好。
- **Weaknesses**：需要引入运行时框架依赖（违反 D2）；发布形态从「单 exe」变成「壳 + 服务 + 端口管理」；
  安全面扩大（本地端口、鉴权、CSRF）；当前没有任何需求要求它。
- **Best fit when**：产品方向变成「启动器 + 常驻服务 + 第三方集成入口」。

## Recommendation

- **Chosen option**：A。
- **Why now**：当前最大的成本不是性能也不是功能，而是**改动风险**——任何一次规则调整都要在 2000 行文件里找位置，
  任何一次重构都没有离线测试网兜底。选项 A 用最小运行形态变化换来「纯逻辑可测 + 边界可查 + 扩展点明确」。
- **What must be watched**：迁移期双包并存不能超过两个阶段；AST 守卫必须真的进 CI，否则边界会在半年内腐化；
  前端 ES 模块化必须保住 `window.__aurora` 测试面，否则现有 90 项 e2e 判据会失效。

## Evidence vs assumptions

- **证据**：行数与文件数、桥接方法清单、线程清单、数据文件统计、外部集成清单均来自当前代码（见 `README.md` 基线表）。
- **假设**：维护者仍是单人为主（社区只提 PR）；Textractor / LE 继续「只对接不打包」；用户规模不要求多窗口或云同步。
- **待确认**：未来是否真的需要后台常驻服务形态（若需要，选项 D 会重新进入候选，见 `04` 的触发条件）。

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 迁移期双轨 | `gl` shim 与新包并存，易被误改 | shim 只做转发、带 `DeprecationWarning`，`13-roadmap` P1 结束后删除 |
| 只分目录不分职责 | 目录变了、`api.py` 逻辑照搬 | P3 验收要求：桥接 mixin 内不得出现业务分支与 IO |
| 守卫被绕过 | 有人图快直接 import | AST 守卫进 CI，违反即红；例外需 ADR |

## Recommended next skill

`quality-attribute-scenario-writer` → 见 [`02-quality-attributes.md`](02-quality-attributes.md)。
