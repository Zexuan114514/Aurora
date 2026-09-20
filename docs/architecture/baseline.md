# P0 基线（Baseline，2026-09-20）

## Summary

P0 把「今天的 Aurora」变成了可断言的数字与文件：**契约快照、去敏库夹具、探针清单、架构基线、
离线检查 + CI 骨架**。之后每个阶段结束时，只要 `python tools\checks\run_all.py` 仍然全绿，
就说明没有把既有行为改坏。

## 冻结了什么

| 产物 | 位置 | 作用 |
| --- | --- | --- |
| 桥接 / 事件契约快照 | [`contracts/bridge-contract.json`](contracts/bridge-contract.json) | 105 个公开桥接方法（含参数与返回标注）+ 41 个内部方法 + 4 个悬浮窗方法 + 14 个事件主题 + 8 个悬浮窗动作 |
| 去敏库夹具 | [`../../tests/fixtures/library-v1.sanitized.json`](../../tests/fixtures/library-v1.sanitized.json) | 由真实库伪名化而来：24 游戏 / 63 字段并集 / 123 会话 / 39 设置项，供 P2 迁移测试逐字段断言 |
| 夹具清单 | `tests/fixtures/fixture-manifest.json` | 计数、去敏规则、必须保持的不变量、泄露反查项 |
| 探针脚本清单 | `tools/checks/tools-manifest.json` | 29 个脚本的类别（离线 / 本机进程 / 联网 / 真机 / 构建 / 辅助）与既有结论 |
| 架构基线 | `tools/checks/baseline.json` | 37 个模块的行数、20 个具名线程、桥接计数、数据与产物体积、容差与「搬家登记表」 |
| 离线检查 | `tools/checks/run_all.py` | 6 项守卫，零依赖、无网络，可直接在 CI 跑 |
| pytest 包装 | `tests/test_offline_checks.py` + `pytest.ini` | 把同样的检查接进标准测试流程 |
| CI | `.github/workflows/offline-checks.yml` | windows-latest / Python 3.13：先跑零依赖检查，再跑 pytest，并归档结果 JSON |

## 基线数字（2026-09-20）

| 指标 | 基线 |
| --- | --- |
| 公开桥接方法 | 105（前端调用点 96，另 9 个由本体/工具调用） |
| 内部方法 | 41 |
| 悬浮窗桥接方法 / 动作 | 4 / 8 |
| 事件主题 | 14 |
| 代码规模 | `main.py` + `gl/` 共 24 个 Python 模块；`app.js` 3688 行、`app.css` 1954 行、`index.html` 845 行 |
| 数据 | 库 290 KB / 24 游戏 / 60–62 字段每游戏（并集 63）/ 39 设置项 / 123 会话 / 426 图片记录 |
| 具名线程 | 20 个（去重后；基线清单 21 行，含一处双文件重复） |
| 产物 | `Aurora.exe` 24.3 MB |
| 可选的运行时依赖 | Pillow（仅存 PNG / 转 .ico，缺失时降级）；硬依赖仍只有 pywebview + winrt |

## 本机能力快照（2026-09-20，非 CI 门槛）

| 能力 | 结果 | 对基线的意义 |
| --- | --- | --- |
| Edge WebView2 | 已安装 | 默认内核路径可测；Qt 回退路径需要单独开关验证 |
| Locale Emulator | **已装到 `E:\Locale.Emulator.2.5.0.1`**（2026-09-20 补测：四件套校验通过、`-run` / `-runas` 命令拼装正确、`LEConfig.xml` 读到「Run in Japanese」与「Run in Japanese (Admin)」两套配置） | 真机转区可测；注意 `detect()` 不会自动扫 E 盘这类自定义目录，需要在 设置 → 转区启动 里指定 `…\LEProc.exe`，或设 `le_proc_path` |
| TextractorCLI | 已找到（x86 与 x64 两个版本都在） | 钩子链路可真机回归（`vntext_live.py`） |
| 外部解压器 | WinRAR `UnRAR.exe` | `.rar/.7z` 自动解压可测；`.zip` 走标准库 |
| Windows OCR 语言 | `en-US` / `ja` / `zh-Hans-CN` | 日语 OCR 可用，OCR 回退路径可真机测 |
| 数据目录 | 项目同级 `data/`，可写 | 与「优先程序目录」的解析顺序一致 |

> 这六个值只反映当前这台开发机，用于判断「哪些验收能本地做、哪些要另找环境」；
> CI 不检查它们，能力探测本身的行为由 `11-availability-and-degradation.md` 的矩阵约束。

## 怎么用

```powershell
python tools\checks\run_all.py                  # 6 项离线检查（CI 主线）
python tools\checks\run_all.py --json out.json  # 附带机器可读结果
python -m pytest                                # 同一批检查的 pytest 包装
```

单项检查也可以单独跑，例如 `python tools\checks\check_contract.py`（改动桥接前后最该跑的一个）。

## 每项检查在防什么

| 检查 | 防的事 | 失败时该怎么办 |
| --- | --- | --- |
| `check_contract` | 桥接方法改名 / 参数漂移 / 新事件没登记（ADR-0006） | 同步 `contracts/bridge-contract.json`；改名必须走 ADR |
| `check_dependencies` | 悄悄引入新的运行时依赖（ADR-0003） | 用标准库实现，或写 ADR 并更新白名单 |
| `check_fixture` | 夹具被改坏 / 混进真实游戏名与密钥 | 重新生成夹具并更新 `fixture-manifest.json` |
| `check_tools_manifest` | 新增探针脚本没有登记、清单里留了已删脚本 | 补 `tools-manifest.json` 条目（kind / phase / expected） |
| `check_architecture_baseline` | 模块被静默删除、行数暴涨、线程表失控 | 在 `baseline.json` 的 `superseded_by` 里登记搬家，或说明体积变化 |
| `check_layers` | 越过分层的 import、绕过 `call()` 的桥接调用、改写 `sys.path` | 按 `05-layers-and-rules.md` 放到正确的层；例外写 ADR |

## 与后续阶段的关系

- **P1 起**：`aurora/` 目录一出现，`check_layers` 会自动开始执行 domain 纯净性、ui/app 不得 import infra 等规则；
  搬家的模块写进 `baseline.json.superseded_by`，检查就会从「模块消失」的失败降级为一条记录。
- **P2 起**：`tests/fixtures/library-v1.sanitized.json` 是迁移测试的输入，断言迁移前后字段、时长、会话全等。
- **P4 起**：前端拆分后 `check_contract` 继续盯 96 个调用点；`e2e.py`（90 项）与 `visual.py` 仍是发布前的手动矩阵。
- **P6 起**：`docs/engines.md` 的实测表格由规则包生成，`tools-manifest.json` 里登记的 `vntext_live.py` 结论作为验收。

## Evidence vs assumptions

- **证据**：本页所有数字都由 `tools/checks/*` 从当前代码与数据现场采集（可复跑）；夹具的反查项包含原始标题、路径、
  商店域名、用户名与密钥串。
- **假设**：离线检查在 Windows 与 Linux 上都能跑（只用标准库与 `pathlib`）；CI 用 windows-latest 是因为后续阶段
  会加入 Windows 相关的离线用例（PE 头解析、注册表读取的替身）。
- **不确定**：冷启动耗时尚未纳入自动基线（需要真实启动界面）→ 目前记录 exe 体积与模块规模，
  等 P1 接入启动打点后在 `baseline.json` 里补 `boot_ms`。

## 验收

- `python tools\checks\run_all.py` → **6/6 通过**。
- `python -m pytest` → **7 passed**。
- 契约快照与今日代码一致：105 公开方法 / 96 前端调用点 / 4 悬浮窗方法 / 14 事件主题，**零差异**。
