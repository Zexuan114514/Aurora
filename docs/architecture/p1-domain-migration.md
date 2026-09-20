# P1 交付记录：纯逻辑下沉到 `aurora/domain`

## Summary

P1 把四处**纯逻辑**从 `gl/` 搬到 `aurora/domain/`，`gl/` 原位置改成同名转发 shim，
用 **82 个金样本用例**卡住「搬完行为逐字一致」。分层守卫在 `aurora/` 出现后自动激活，
现在 domain 的纯净性（无 IO、无 ctypes/webview、无跨层 import）由 CI 强制。

| 指标 | 迁移前 | 迁移后 |
| --- | --- | --- |
| `gl/vntext.py` | 2145 行 | 1359 行（纯规则 682 行 → `domain/text_rules.py`，引擎规格 279 行 → `domain/engine_rules.py`） |
| `gl/detect.py` | 221 行 | 23 行（转发 shim → `domain/matching.py`） |
| `gl/sources/base.py` | 148 行 | 45 行（`Candidate` / `Metadata` → `domain/contracts.py`） |
| `gl/sources/manager.py` | 430 行 | 378 行（打分判定 → `domain/matching.py`） |
| `gl/process.py` + `gl/api.py` | 内联会话公式 | 改用 `domain/session_rules.py` |
| 金样本 | — | 82 个用例（4 个 golden 文件） |

## 搬了什么、留在哪

| 新位置 | 内容 | 原位置 | 留在原地的部分 |
| --- | --- | --- | --- |
| `aurora/domain/text_rules.py` | 折叠重复书写、去重、折行拼接、说话人合并、OCR 整理、乱码/噪声/刷屏判定、变体并合 | `gl/vntext.py` 的纯函数段 | TextractorCLI 子进程与 UTF-16 协议、OCR 采样循环、`VnTextEngine` 状态机 |
| `aurora/domain/engine_rules.py` | 引擎清洗档位、引擎签名、实测指纹表、H-code 拼装/校验/解析 | `gl/vntext.py` 的规格段 | 读 exe 算 CRC32（`file_fingerprint`）、CLI 探测（`find_cli` / `cli_builds`）、按 PID 探测引擎 |
| `aurora/domain/matching.py` | 路径 → 关键词推断、名称归一化、相似度、候选打分与采纳判定 | `gl/detect.py` 全部 + `gl/sources/manager.py` 的 `_score` / `_acceptable` / `_secondary_penalty` | 资料源实现、跨源补图、缓存与重试（`infra` 侧，P3 再搬） |
| `aurora/domain/contracts.py` | `Candidate` / `Metadata` 数据模型与合并逻辑 | `gl/sources/base.py` | `Source` 基类（带插件发现语义，P6 再定归属） |
| `aurora/domain/session_rules.py` | 会话时长口径、崩溃恢复补记、入账阈值 | `gl/process.py::_finalize` 的内联公式、`gl/api.py::_recover_sessions` 的内联公式 | 进程树监控、心跳线程、子进程管理 |

## 契约与转发

- **同名转发**：`gl/vntext.py` / `gl/detect.py` / `gl/sources/base.py` / `gl/sources/manager.py`
  仍然是老调用点的入口，且测试断言它们与 domain 指向**同一个函数对象**（不允许两份实现各自演化）。
- **不改变对外行为**：桥接方法名、事件主题、`data/library.json` 字段全部未动，
  `tools/check_bridge.py` 仍是「后端缺失：无」。
- **domain 纯净性**（`tools/checks/check_layers.py`，`aurora/` 存在即启用）：
  domain 文件不得 import `ctypes` / `webview` / `subprocess` / `threading` / `urllib` / `infra` / `ui` / `platform`，
  也不得调用 `open` / `eval` / `exec`；`ui` / `app` 不得直接 import `infra`。

## 金样本（82 个用例）

| 文件 | 用例数 | 覆盖 | 捕获方式 |
| --- | --- | --- | --- |
| `tests/fixtures/golden/text_rules.golden.json` | 39 | DRACU RIOT 三形态重复、BGI 缺字并合、Escu:de 折行、说话人合并、OCR 噪声、刷屏判定、`「あ…」` 短句 | 迁移前调用 `gl.vntext` 现成实现逐条捕获 |
| `tests/fixtures/golden/engine_rules.golden.json` | 15 | 引擎档位、WillPlus/Artemis 实测码拼装、指纹命中/未命中、H-code 规范化比对、handle 行解析 | 同上 |
| `tests/fixtures/golden/matching.golden.json` | 16 | 日文/英文路径推断、`norm` / `tokens` / `similarity`、精确与噪声候选打分、采纳判定 | 迁移前调用 `gl.detect` 与 `gl.sources.manager` |
| `tests/fixtures/golden/session_rules.golden.json` | 12 | 正常退出、`gone_at` 优先、`ended_at`/`now` 兜底、起始缺失、负数夹零、心跳补记与截断、入账阈值 | `ProcessManager._finalize` 实跑 + 现有内联公式 |

> 注意一条口径：`_finalize` 会把 `ended_at` 覆写成当前时刻，所以「没有 `gone_at`」的用例
> 无法用实跑结果做金样本（会随墙上时钟漂移），这类用例按**现有公式**给出期望值并在文件里注明来源。

## 验收证据（2026-09-20）

| 检查 | 结果 |
| --- | --- |
| `python -m pytest` | **15 passed**（6 项离线检查 + 4 组金样本 + 4 项转发/接线断言） |
| `python tools\checks\run_all.py` | **6/6 通过**；分层守卫报告「aurora/ 规则已启用：domain 6 个文件」 |
| `tools/check_bridge.py` | 后端缺失：无（105 公开方法 / 96 前端调用点未动） |
| `tools/vntext_probe.py` | 全部通过（假 CLI 协议 + 真实清洗规则 + 缓存/术语表/OCR 状态） |
| `tools/session_probe.py` | 全部通过（进程树判定、时长结算、启动次数、LE argv 透传） |
| `tools/selftest.py` | 10/10 命中 |
| `tools/meta_offline.py` | 本地缓存元数据解析通过 |
| `tools/checks/baseline.json` | 已记录 P1 的模块行数变化、7 个新增 domain 文件与 82 个金样本用例数 |

## Evidence vs assumptions

- **证据**：所有行数、用例数、探针结论都可在本机复跑；金样本是迁移前捕获的，不是事后手写。
- **假设**：`gl/` 的转发 shim 会保留到 P3 结束（`13-roadmap` 的约定），因此老 import 路径短期不会移除。
- **不确定**：`Source` 基类与资料源注册表归属 domain 还是 infra，留到 P6 定；
  当前 `contracts.py` 只搬数据模型，避免 domain 依赖插件发现逻辑。

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 转发层长期存在 | 两套 import 路径会让人迷惑 | shim 文件头写明「P1 转发 + P3 收口」，并在 P3 一并删除 |
| 金样本只是「当时正确」 | 规则本身有错也会被固化 | 金样本保护的是**重构不改行为**；规则修正另配用例（真机探针 + README 实测记录） |
| 拆分粒度 | `text_rules` 682 行仍偏大 | 若 P3 后再增长，按「折叠 / 判定 / OCR」再分三个模块，拆分标准写在 `05-layers-and-rules.md` |

## Next

**P2 数据 v2**：`state/{settings,library}.json` + `sessions.jsonl`、单写者与去抖、
迁移器（用 `tests/fixtures/library-v1.sanitized.json` 做全等断言）与回滚路径。
