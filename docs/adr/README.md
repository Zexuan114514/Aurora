# 架构决策记录（ADR）索引

本目录按 `software-architecture-skills-main` 的 `adr-writer` / `adr-template.md` 组织。
每条 ADR 记录**背景、驱动、考虑过的选项、决定、后果与后续动作**；状态变更直接改文件里的「状态」行，
不重写历史。

| 编号 | 标题 | 状态 |
| --- | --- | --- |
| [ADR-0001](ADR-0001-modular-monolith.md) | 采用模块化单体，不拆进程/服务 | 已接受 |
| [ADR-0002](ADR-0002-pywebview-no-build-frontend.md) | 保留 pywebview 与无构建前端 | 已接受 |
| [ADR-0003](ADR-0003-zero-new-runtime-deps.md) | 运行时零新增依赖 | 已接受 |
| [ADR-0004](ADR-0004-data-partitioning-v2.md) | 数据分账与 schema 版本化 | 已接受 |
| [ADR-0005](ADR-0005-assets-single-source.md) | 资产单一来源（本地静态资源服务） | 已接受 |
| [ADR-0006](ADR-0006-bridge-contract-freeze.md) | 桥接方法名冻结 + 事件信封 | 已接受 |
| [ADR-0007](ADR-0007-task-runner.md) | 显式任务执行器替代散落线程 | 已接受 |
| [ADR-0008](ADR-0008-declarative-engine-rules.md) | 引擎规则与 hook 码声明式 JSON 化 | 已接受 |
| [ADR-0009](ADR-0009-plugin-api-v1.md) | 插件 API v1（进程内、无沙箱） | 已接受 |
| [ADR-0010](ADR-0010-structured-logging.md) | 结构化日志与诊断包（脱敏） | 已接受 |
| [ADR-0011](ADR-0011-credential-storage.md) | 密钥明文存储 + 导出剥离 | 已接受 |
| [ADR-0012](ADR-0012-packaging-manifest.md) | 打包清单单一来源 | 已接受 |
| [ADR-0013](ADR-0013-frontend-build-chain-and-themes.md) | 前端构建链（Vue + Element Plus）与主题系统（现为五套） | 已接受（第 3 条「新旧并行」已被 ADR-0014 取代） |
| [ADR-0014](ADR-0014-drop-v1-frontend.md) | 删除 v1 前端（无构建 ES 模块） | 已接受 |

相关文档：架构总览 [`../architecture/README.md`](../architecture/README.md)，
落地路线 [`../architecture/13-roadmap.md`](../architecture/13-roadmap.md)。
