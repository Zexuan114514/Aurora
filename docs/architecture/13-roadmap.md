# 13 落地路线（roadmap）

## Summary

8 个阶段，每阶段都能独立发布、独立回滚。原则：**先冻结契约，再搬纯逻辑，再动数据，最后才动边界与前端**；
每一阶段结束都必须让现有真机探针保持通过。

## 阶段总览

| 阶段 | 目标 | 主要交付 | 验收（必须全过） | 回滚方式 |
| --- | --- | --- | --- | --- |
| **P0 基线冻结** ✅ | 让「现状」变成可断言的数字 | 契约快照（105 + 4 方法、14 事件）；去敏库夹具；能力/线程/体积基线；`tests/` + 离线检查与 CI 骨架 | 快照与今日行为一致；`run_all.py` 6/6、`pytest` 7 passed | 仅新增文件，删掉即回滚 |
| **P1 纯逻辑分层** ✅ | 把规则从 IO 里剥出来 | `aurora/domain/*`（文本规则、匹配打分、引擎规则、会话结算）；`gl` 转发 shim | 82 个金样本逐字一致；`pytest` 15 passed；`selftest.py` 10/10、`meta_offline.py`、`vntext_probe.py`、`session_probe.py` 通过 | 删除 `aurora/`，恢复原 import |
| **P2 数据 v2** ✅ | 让数据可迁移、可恢复、写入成本降到常量级 | `state/{settings,library}.json` + `state/sessions.jsonl`；迁移器 + 备份 + `--check`；单写者 + 去抖 | 迁移全等断言；去抖与强杀不损坏；回滚可用；导入/导出兼容且脱敏 | 用备份回到 v1 文件；代码回退版本 |
| **P3 用例服务化 + 桥接 mixins** 🔶 | 拆掉 2232 行的 `api.py`，契约零漂移 | P3.1/P3.2 已完成：`ui/bridge/{window,shell,settings}.py`（41 个方法，`api.py` → 1808 行）；P3.3：其余方法 + `app/services` + `TaskRunner`/`EventBus` | 契约 diff = 0；`check_bridge.py` 无缺失；真机启动/翻译/钩子查找抽测通过 | 按 mixin 粒度回退到旧方法实现 |
| **P4 前端 ES 模块化** | 3688 行 IIFE → 模块 + 单一状态层 | `ui/web/app/**`；`core/api.js`、`core/store.js`；打包清单单一来源 | `e2e.py` 90/90；`visual.py` 全过；`__auroraErrors` 为空 | 保留旧 `app.js` 一个版本，按开关回退 |
| **P5 资产服务化** | 资产单一来源，取消 web 目录复制 | `infra/webserver.py`；`/assets/` 映射；删除 `sync_user_assets` | 双内核下封面/背景/图标正常；越权与穿越用例被拒 | 开关回退到「复制到 web 目录」的旧机制 |
| **P6 插件与规则包** | 让社区贡献不需要读核心代码 | `data/plugins/*` + manifest；`data/rules/engines/*.json`；`docs/engines.md` 自动生成 | WillPlus/Artemis 实测码从规则包带出；`vntext_live.py` 真机通过 | 保留内置规则为默认，关掉插件目录加载 |
| **P7 治理收口** | 让边界与契约长期不腐化 | CI 全量（单元/契约/迁移/守卫/打包 dry-run）；诊断包；README 与开发文档同步 | 离线检查全绿；真机矩阵无退化；故意违规能让 CI 变红 | 关闭新检查（不推荐），或回退对应阶段 |

## 每阶段的固定动作

1. **开始前**：跑一次基线（`tools/check_bridge.py` + 本阶段相关探针），把结果留档。
2. **进行中**：只做本阶段范围内的改动；跨阶段需求进待办，不在迁移期顺手"优化"。
3. **结束前**：契约快照 diff、层级守卫、相关探针、文档同步四项检查。
4. **发布**：exe 体积与冷启动耗时与 P0 基线对比；差异超 20% 需在阶段报告里解释。

## 真机 / 联网验收矩阵（每个涉及相应子系统的阶段都要跑）

| 脚本 | 覆盖 | 期望 |
| --- | --- | --- |
| `tools/e2e.py` | 大厅 / 游戏页 / 设置 / 分类 / 拖拽 / 缩放 / 布局 | 90/90 |
| `tools/visual.py` + `visual_summary.py` | 封面与缩略图真实渲染、环形层次 | 判据全过 |
| `tools/selftest.py` | 文件名推断 + 多源匹配 | 10/10 |
| `tools/test_multisource.py` | 多源兜底 | 21/21 |
| `tools/vntext_live.py`（hook / OCR） | 真机取词 + 翻译 | 全部干净 + 有译文 |
| `tools/vntext_probe.py` | 清洗规则 / 协议 / 缓存 / 术语表 | 全部通过 |
| `tools/session_probe.py` | 进程树判定、时长结算、LE argv | 全部通过 |
| `tools/download_probe.py` | 资源站、监听、解压、自动入库 | 全部通过 |
| `tools/locale_probe.py` / `net_probe.py` / `theme_probe.py` | 转区 / 网络 / 主题 | 全部通过 |

## 明确不做（本路线范围外）

- 跨平台、安装器、自动更新通道。
- 账号体系、云同步、社区规则在线分发。
- 服务化 / 多窗口 / 第三方 API 开放。
- 前端构建链（Vite/TS）与运行时新依赖。
- 改写清洗与钩子规则本身（本次只搬位置、加回归，不改行为）。

## 阶段状态

| 阶段 | 状态 | 证据 |
| --- | --- | --- |
| P0 基线冻结 | ✅ 已完成（2026-09-20） | [`baseline.md`](baseline.md)：契约快照 + 去敏夹具 + 探针清单 + 架构基线 + `tools/checks/run_all.py`（6/6）+ `.github/workflows/offline-checks.yml` |
| P1 纯逻辑分层 | ✅ 已完成（2026-09-20） | [`p1-domain-migration.md`](p1-domain-migration.md)：82 个金样本 + 转发 shim + 分层守卫激活；`gl/vntext.py` 2145 → 1359 行 |
| P2 数据 v2 | ✅ 已完成（2026-09-20） | [`p2-data-v2.md`](p2-data-v2.md)：state/ 分账 + 迁移器 + 单写者；`pytest` 26 passed；真实库迁移计划 24 游戏 / 123 会话 |
| P3.1 桥接 mixin（窗口 / Shell） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md)：22 个方法搬进 mixin，`api.py` 2232 → 1993 行，契约零漂移 |
| P3.2 其余 mixin + 服务化 + TaskRunner | 待开始 | 同上文档「还没做的」小节列出了范围 |
| P3.2 设置类方法（settings mixin） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节：19 个方法 / 223 行搬出，契约仍 106 方法 |
| P3.3 library / metadata / launch / vntext / downloads + TaskRunner | 待开始 | 同上 |
| P3.3 游戏库类方法（library mixin） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节：37 个方法 / 491 行搬出，`api.py` → 1292 行，契约仍 106 方法 |
| P3.4 metadata / launch / vntext / downloads + TaskRunner/EventBus | 待开始 | 同上 |
| P3.4 元数据 + vntext/钩子/悬浮窗（56 个方法） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节：`api.py` → 309 行（只剩 14 个方法） |
| P3.5 launch / downloads / bootstrap + TaskRunner/EventBus + gl 依赖收口 | 待开始 | 同上 |
| P3.5 启动/会话/下载（10 个方法） | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md)：`api.py` → 160 行（只剩 4 个方法），7 个 mixin |
| P3.6 TaskRunner/EventBus + gl 依赖收口 + app/services 服务化 | 待开始 | 同上「P3.6 剩下」 |
| P3.6 第一批 TaskRunner/EventBus + 平台层 winapi | ✅ 已完成（2026-09-20） | [`p3-bridge-mixins.md`](p3-bridge-mixins.md) 追加小节；`pytest` 31 passed |
| P3.7 线程收编 + 事件总线接线 + 服务化 + 依赖收口 | 待开始 | 同上「P3.7 待办」 |
| P4–P7 | 待开始 | 每阶段结束按「固定动作」四项检查后，把状态与证据补进本表 |

## Evidence vs assumptions

- **证据**：阶段划分严格对齐 `06` 的越界清单与 `05` 的守卫规则；验收项全部是仓库里已有的脚本或本次新增的离线检查。
- **假设**：每阶段可以独立发布；维护者能接受「迁移期不接新功能」的节奏。
- **不确定**：P4/P5 的工作量最大且都涉及界面与资源路径，实际排期要在 P3 结束后回填（届时已有契约与测试网）。

## Recommended next skill

`adr-writer` → 12 条决策见 [`../adr/README.md`](../adr/README.md)。
