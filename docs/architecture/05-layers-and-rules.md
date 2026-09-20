# 05 分层与依赖规则（layered-architecture-designer）

## Summary

目标分层是 **`ui → app → domain`**，`infra → domain`（实现 `app` 定义的端口），`platform` 只提供
Win32 原语，`bootstrap.py` 是唯一组合根。`gl/` 重命名为 `aurora/`，`main.py` 保持唯一进程入口。

## 目标包结构

```
aurora/
  bootstrap.py          组合根：构建 store / 适配器 / 服务 / 桥接，注入 TaskRunner 与 EventBus
  domain/               纯逻辑，无 IO、无 ctypes、无 webview
    library.py          游戏记录、分类书架、状态枚举与不变量
    matching.py         关键词推断与候选打分（现 gl/detect.py + sources/manager._score）
    text_rules.py       文本清洗 / 折叠 / 去重 / 折行拼接 / 说话人合并（现 gl/vntext.py 纯函数段）
    engine_rules.py     引擎规格、指纹匹配、H-code 构造与校验
    session_rules.py    会话结算与时长口径（现 gl/process.py 中的规则部分）
    contracts.py        Metadata / Candidate / PublicGame 等数据形状
  app/
    ports.py            端口 Protocol 定义（见 06）
    services/           library / metadata / launch / vntext / hooksearch / translate / downloads / settings / capabilities
  infra/
    store/              JSON 单写者 + 迁移器 + 备份
    sources/            steam / vndb / bangumi / custom / net（注册表 + 缓存 + 重试）
    textractor/         CLI 子进程、UTF-16 协议、H-code 下发时序
    ocr/                WinRT OCR 适配器
    translate/          LLM / 免费接口 / 缓存 / 术语表
    launch/             启动器、Locale Emulator、进程树、外部解压器
    assets/             封面 / 背景 / 图标落盘与体积治理
    webserver.py        本地静态 + /assets 资源服务
    diagnostics/        结构化日志、环形缓冲、诊断包
  platform/             ctypes 原语：winapi / tray / hotkey / input / capture / memscan / hookfinder
  ui/
    bridge/             按域拆分的 mixins，聚合成单一 js_api 对象（方法名冻结）
    window.py           主窗口、无边框拖拽缩放、主题、托盘联动、拖放绑定
    overlay.py          悬浮窗与其 4 个桥接方法
    events.py           事件信封与前端推送（唯一 evaluate_js 出口）
    web/                前端静态资源（无构建 ES 模块）
```

## 责任矩阵

| 层 | 允许做的事 | 明确禁止 |
| --- | --- | --- |
| `ui` | 参数整形、校验错误码、调用 app 服务、订阅事件、窗口/托盘/热键 | 业务规则、直接读写文件、直接 import `infra`/`platform` 具体实现 |
| `app` | 用例编排、事务边界、超时与取消、事件发布、端口调用 | 依赖 webview、直接 `ctypes`、直接拼 HTTP、直接读 `data/` 路径 |
| `domain` | 纯函数与数据模型、规则判定 | IO、线程、全局状态、`webview`、`ctypes`、`infra`、`ui`、时间与随机（需注入 Clock） |
| `infra` | 实现端口：HTTP、子进程、文件、WinRT、打包资源定位 | 被 `ui`/`app` 直接 import（只能经端口注入） |
| `platform` | Win32 原语封装（句柄、窗口、进程、内存、注册表） | 业务判断、持久化、网络 |
| `bootstrap.py` | 组装一切、生命周期编排（启动/关停顺序） | 承载业务逻辑 |

## 规则（Allowed / Forbidden）

**允许的依赖方向**

```
ui ──▶ app ──▶ domain
              ▲
infra ────────┘        (infra 实现 app.ports，可 import domain)
bootstrap ──▶ 全部     (唯一装配点)
platform ◀── infra     (infra/platform 之间可双向按需，但不得反向进 domain/ui)
```

**禁止的捷径**

1. `ui` 或 `app` 直接 `import aurora.infra.*`（包括 `from aurora.infra.store.json_store import ...`）。
2. `domain` 出现 `ctypes` / `webview` / `socket` / `requests` / `open()` / `subprocess` / `time.time()`。
3. 任何模块在 import 期做 IO（现 `gl/config.py` 的 `DATA_DIR = _default_data_dir()` 就是这种情况）。
4. `ui/bridge` 里出现业务分支（例如「如果引擎是 WillPlus 就…」）或直接操作文件系统。
5. 新增「万能工具模块」`utils.py`（当前 `gl/` 下已有类似趋势）；工具必须挂在明确的域下。
6. 事件不经 `ui/events.py` 直接 `evaluate_js`。

## 横切关注点归属

| 关注点 | 归属 | 形态 |
| --- | --- | --- |
| 路径与数据目录解析 | `infra/store/paths.py` | 函数式解析（不在 import 期执行），结果注入 |
| 日志 | `infra/diagnostics/log.py` | 结构化（级别 + 子系统 + 字段），并提供内存环形缓冲 |
| 配置与设置 | `app/services/settings.py` + `SettingsStore` 端口 | 唯一写者，去抖落盘，变更广播 |
| 能力探测 | `app/services/capabilities.py` + `CapabilityProbe` 端口 | 启动时一次性探测 + 结果缓存 |
| 事件 | `app` 发布 → `ui/events.py` 转发 | `{topic, seq, ts, payload}` 信封 |
| 任务与取消 | `TaskRunner` 端口（app 定义，infra 实现） | 命名、有界、可取消、带超时 |
| 时钟 | `Clock` 端口 | 让会话结算与缓存 TTL 可测 |

## 守卫（arch guard）

| 规则 | 检查方式 | 违反后果 |
| --- | --- | --- |
| `domain` 无 IO / 无第三方 | AST 扫描 import 名与调用名（`open`、`subprocess`、`ctypes`、`webview`…) | CI 红 |
| `ui`/`app` 不 import `infra` | AST 扫描模块级 import 前缀 | CI 红 |
| import 期无副作用 | 在隔离进程里 import 每个模块，断言没有文件/网络/线程产生 | CI 红 |
| 文件规模阈值 | 单文件 ≤ 600 行（`web/` 前端模块 ≤ 400 行）；例外需 ADR | CI 黄（P4 起转红） |
| 桥接契约 | 与 `contracts/bridge-contract.json` 对比方法名集合 | CI 红 |

## Evidence vs assumptions

- **证据**：`gl/config.py` 的 import 期目录解析、`gl/api.py` 的素材文件操作、`gl/vntext.py` 的规则与 IO 混排，
  都是当前代码里可验证的越界行为；目标结构按「把已有职责搬对位置」拆，不新增职责。
- **假设**：无需为跨平台预留抽象层（Windows-only 是明确约束）；前端保持无构建，因此 `web/` 不参与 Python 分层守卫。
- **不确定**：`platform/` 与 `infra/` 的边界在 `hookfinder`（调试器 + 采样 + 记录）上会略显模糊，
  约定：**线程/句柄/内存读写属 `platform`，候选筛选与判定属 `domain`，会话编排属 `app`**。

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 分层变成教条 | 为了「不 import infra」写出过度抽象的包装 | 端口只在下述场景引入：需要替换实现、需要离线测试、需要跨子系统复用 |
| 迁移期双包 | `gl` shim 与新包并存导致「改了旧的」 | shim 只转发 + 运行期告警；P1 末尾删除 |
| 守卫误伤 | `tools/` 脚本本来就该直接 import 具体实现 | 守卫只覆盖 `aurora/`，`tools/` 与 `tests/` 豁免 |

## Recommended next skill

`component-boundary-reviewer` → 见 [`06-component-boundaries.md`](06-component-boundaries.md)。
