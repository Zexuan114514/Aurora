# 开源化 P1 交付记录：社区贡献通道

日期：2026-09-27
对应行动清单：维护者本地的《Aurora 开源化行动清单》P1（社区杠杆：解锁「别人能贡献」；
该清单不入库，公开可查的部分见本目录 `p0-open-source.md` 与本文件）

> 注意区分两套编号：本目录的 `p1-domain-migration.md` 是架构改造阶段的 P1；
> 这份记录对应**开源化行动清单**的 P1。

## 已落地

### 引擎实测规则：一等公民贡献通道

- **导出入口**：设置 → 关于 → **导出我的引擎规则**（桥接方法 `export_engine_rules()`）。
  服务在 `aurora/app/services/rule_export.py`，产物写到 `data/rules/export/`：

  | 文件 | 内容 |
  | --- | --- |
  | `Aurora-engine-rules-<时间戳>.json` | 规则包本体，schema `aurora.engine-rules/1`，与内置包同构 |
  | `Aurora-engine-rules-<时间戳>.md` | 按 issue 表单栏目排好的投稿说明，直接粘贴 |

- **数据来源**：游戏库里保存过的实测 hook 码（`vntext_hook`，钩子查找器验证通过才写进去）
  + `data/rules/engines/*.json` 用户规则包。导出时读一次游戏 exe 算
  `(文件名, 字节数, CRC32)` 指纹；读不到 exe 或 H-code 解析不了的条目进说明文件末尾的「没能自动整理的部分」，不静默丢。
- **去重提示**：指纹命中内置包的条目会在说明里标注「不用重复提交」。
- **纯函数下沉**：`aurora/domain/engine_rules.py` 新增 `rule_id()` 与 `parse_hook_code()`；
  `tools/export_engine_rules.py` 改用同一个 `rule_id`（原来各写一份 slug 规则）。
- **issue 表单**：`.github/ISSUE_TEMPLATE/engine-rule.yml`，栏目直接对应 `hooks.json` 字段
  （游戏名 / 引擎 / exe 文件名 / 字节数 / CRC32 / H-code / 原文样例 / 是否转区 / 是否缺字 / 规则包）。

### Issue / PR 模板

- `bug_report.yml`：**诊断包为必填字段**（这是相对同类项目最省事的一条规矩：`tools/collect_diagnostics.py`
  生成的 zip 里已有脱敏设置、日志尾巴、插件与资料源状态）。
- `feature_request.yml`：多一栏「你愿意自己动手吗」——愿意接的人会被指路，不愿接也不影响被采纳。
- `engine-rule.yml`：见上。
- `config.yml`：关掉空白 issue，把「手册 / 贡献指南 / 安全说明」顶到入口。
- `.github/PULL_REQUEST_TEMPLATE.md`：三条门禁（`run_all.py` / `pytest` / 前端构建）+ 实测环境 + 素材边界。

### 贡献与安全文档

- `CONTRIBUTING.md` 重写：三条路径（引擎规则 / 插件 / 核心代码）+ 三个坑（bat 必须 GBK+CRLF、
  `data/` 不进仓库且前端要 `npm run build`、改动必须过 `run_all.py` + `pytest`）+ inbound = outbound（MIT）。
- `SECURITY.md`：私密上报渠道、支持范围、**插件信任模型**（同进程同权限、宿主只保证「插件出错不带崩 Aurora」）、
  Aurora 的读写边界（只读内存找文本、不注入 DLL、不代下外部工具）、未签名程序的说明。
- `CODE_OF_CONDUCT.md`：Contributor Covenant v2.1 的中文摘要 + 执行方式（并明确「做不到就别挂」）。

### 守卫

- 新增第 15 项离线检查 `tools/checks/check_github_templates.py`：四份表单在位且字段齐备、
  `bug_report` 的诊断包必须必填、引擎规则表单覆盖指纹字段并指向导出入口、PR 模板提到三条门禁、
  三份根文档在位；CONTRIBUTING 必须写清三个坑，SECURITY 必须写清插件边界。
- 契约快照（`contracts/bridge-contract.json`）与前端测试面快照（`contracts/frontend-surface.json`）
  按新方法 / 新按钮刷新。

## 验收（本地）

- `python tools\checks\run_all.py`：**15 项全过**（新增贡献通道守卫）。
- `python -m pytest`：**133 项全过**（新增 `tests/test_rule_export.py`：H-code 解析往返、
  id 与内置包一致、导出包通过规则校验、坏码 / 丢 exe 进 skipped、内置重复标注）。
- `cd frontend && npm run build`：产物入库 `gl/web/v2/`（构建指纹由 `check_frontend_build.py` 守）。
- 装配冒烟：以临时数据目录构造 `Api()` 并调用 `export_engine_rules()`，两个文件正常落盘、schema 正确。
- `tools/e2e.py` 新增「关于页能导出引擎规则」一步（真机全量复跑属发布前动作，未在本轮执行）。

## 下一步

- 把「手柄导航 / 沉浸式全屏 / 存档管理」写成三个**「欢迎认领」issue**：
  现象 → 期望结果 → 从哪个文件开始 → 验收清单 → 合并后署名。
- 转入开源化 P2：工作区收干净、文档一致性收口（DOM id / ADR 计数、路线图口径）、删一次性脚本。
