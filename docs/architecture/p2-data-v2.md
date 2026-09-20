# P2 交付记录：数据 v2（分账 / 迁移 / 单写者）

## Summary

P2 把「一个 `data/library.json`、改一个设置就全量重写」换成 **state/ 三件套 + 单写者 + 去抖**，
并给出可干跑、可备份、可回滚的 v1→v2 迁移。老代码路径（`gl/store.py` 的 `Library`、`gl/api.py` 的
导入导出、`gl/linetrans.py` 的术语表）全部接到新实现上，前端与桥接契约不变。

| 项 | 之前 | 之后 |
| --- | --- | --- |
| 状态文件 | `data/library.json`（289 KB，单文件） | `data/state/settings.json` + `state/library.json` + `state/sessions.jsonl` |
| 改一个设置 | 重写整个库（全部游戏记录） | 只重写 `settings.json`（常量级） |
| 会话历史 | 内嵌在每条游戏记录的 `sessions` 数组 | 追加式 `state/sessions.jsonl`（内存只留最近 50 条） |
| 写入时机 | 每次修改同步全量写 | 去抖 300ms / 设置 500ms；会话结束、启动/结束游戏、退出前强制落盘 |
| 备份 | 无 | 覆盖已有文件前自动备份到 `state/backup/`（每文件每进程一次，保留最近 3 份） |
| 损坏处理 | 返回默认值，可能静默丢数据 | 用最近备份恢复 + 损坏文件改名留档 |
| 迁移 | 无（`"version": 1` 只是标记） | 检测 → 干跑计划 → 备份 → 拆分 → 回读校验 → 提交，v1 原文件搬进备份目录 |
| 导出 | 含 `translate_api_key` 明文 | 剥离密钥 + 带 `schema_version: 2`（ADR-0011） |
| 术语表 / 日志 | `data/glossary.json`、`data/aurora.log` | `data/vntext/glossary.json`、`data/logs/aurora.log`（首次启动自动搬日志，术语表保留旧文件兜底） |

## 目录布局

```
data/
  state/
    settings.json        # { schema_version: 2, settings: {...} }（含密钥）
    library.json         # { schema_version: 2, games: [...], bookshelves: [...] }
    sessions.jsonl       # 每行一次会话：{game_id, ts_start, ts_end, seconds, source}
    backup/              # library-v1-<ts>.json（迁移前复制）/ library-v1-legacy-<ts>.json（v1 原件）
                         # settings-pre-write-<ts>.json / library-pre-write-<ts>.json（覆盖前备份）
  vntext/glossary.json   # 术语表（旧 data/glossary.json 仍可读）
  logs/aurora.log        # 结构化前的文本日志（旧 data/aurora.log 首次启动搬过来）
  cache/  webview/  downloads/  covers/  backgrounds/  icons/    # 位置不变
```

> 素材目录（`covers/backgrounds/icons`）**刻意没动**：它们的搬迁与「取消 web 目录复制」一起做才安全，
> 属 P5（资产服务化）。`contracts/data-schema-v2.md` 已同步标注。

## 迁移规则

| 步骤 | 行为 | 失败时 |
| --- | --- | --- |
| 1 检测 | `state/` 里有文件 → v2；只有 `data/library.json` → v1；都没有 → fresh | —— |
| 2 计划 | `python main.py --check-migration` 只读输出：游戏数 / 分类数 / 设置项 / 会话数 | v1 不可解析 → 明确报错，退出码 2 |
| 3 备份 | 复制 v1 到 `state/backup/library-v1-<ts>.json` 并校验 sha256 | 备份失败 → 中止，不写任何 v2 文件 |
| 4 拆分 | settings → `settings.json`；games+bookshelves → `library.json`；内嵌 sessions → `sessions.jsonl`（带 `source: migrated-v1`） | —— |
| 5 校验 | 回读三个文件，断言设置项数与游戏数与迁移前一致 | 不一致 → 删除已写文件并抛错 |
| 6 提交 | v1 原文件 `os.replace` 进 `state/backup/library-v1-legacy-<ts>.json`（不留两份真相） | 移动失败 → 保留 v1 文件并在报告里注明 |
| 7 附带 | 术语表复制到 `vntext/glossary.json`；日志在 `ensure_dirs()` 里搬到 `logs/` | —— |

**回滚三步**：① 把 `state/backup/library-v1-<ts>.json` 复制回 `data/library.json`；
② 删除（或改名保留）`data/state/`；③ 用旧版 exe 启动。

## 写入模型

- **单写者**：`aurora/infra/store/state.py` 的 `StateStore` 持有唯一写线程（`aurora-state-writer`），
  所有落盘都经过它；`Library` 只改内存快照再 `mark_dirty()`。
- **按文件去抖**：库 300ms、设置 500ms；`flush()` 立刻写（会话结束 / 启动结束游戏 / 退出）。
- **原子写**：`*.tmp` → `flush` + `os.fsync` → `os.replace` → 回读校验；失败抛错不静默。
- **覆盖前备份**：准备覆盖已存在的文件时先存一份 `*-pre-write-<ts>.json`，各保留最近 3 份。
- **损坏恢复**：解析失败时用最近匹配备份恢复，原文件改名 `*.corrupt-<ts>.json` 留档。
- **端口**：`aurora/app/ports.py` 定义 `Clock` / `StateStorePort`；`StateStore` 是它的 JSON 实现，
  P3 的服务直接依赖端口而不是实现。

## 验收证据（2026-09-20）

| 检查 | 结果 |
| --- | --- |
| `python -m pytest` | **26 passed**（含 `tests/test_state_store.py` 的 10 项 P2 用例） |
| 迁移全等 | 用去敏夹具（24 游戏 / 63 字段并集 / 123 会话 / 39 设置）逐游戏逐字段断言，字段集合与取值零差异 |
| 会话摊平 | `sessions.jsonl` 恰好 123 行，`seconds` 合计与迁移前一致，全部带 `source: migrated-v1` |
| 备份 | 迁移后备份 sha256 == 源文件 sha256（`atomic.checksum` 断言） |
| 干跑 | `migrations.plan()` / `apply(plan_only=True)` 都不创建 `state/`，v1 文件保持原位 |
| 去抖 | `mark_dirty(settings_only=True)` 后文件未出现，`flush()` 后出现且无残留 `.tmp` |
| 损坏恢复 | 手工写坏 `state/library.json` → 新实例从 `pre-write` 备份恢复，损坏文件留档 |
| 导出脱敏 | `export_payload(redact=True)` 里 `translate_api_key` 为空、原值不出现在 JSON 中 |
| 导入合并 | 同 exe 跳过、新 exe 加入、分类按名字合并新建（1 新建 / 1 新增 / 1 跳过） |
| 回滚 | 备份放回 `data/library.json` + 删除 `state/` → 重新迁移出同样的 24 游戏 |
| `tools/checks/run_all.py` | **6/6**（契约快照、依赖白名单、夹具、探针清单、基线、分层守卫） |
| 真实库迁移计划 | `python main.py --check-migration` → 24 游戏 / 0 分类 / 39 设置项 / 123 会话，等首次启动执行 |

## 契约变更

- 新增公开桥接方法 `shutdown()`（Python 侧生命周期钩子：停文本会话与下载监听 → 落盘 → 关停写线程），
  公开方法 **105 → 106**；前端调用点仍 96，事件主题仍 14。
- 新增 `tools/checks/update_contract.py`：契约快照刷新工具（默认干跑，`--write` 才写），
  避免「手工编辑快照」这类不可复现操作。
- 基线扫描修掉一个正则误报：`save_filename="aurora-library.json"` 曾被当成线程名，线程清单回到 20 条。

## 明确延后

| 项 | 为什么延后 | 落在哪 |
| --- | --- | --- |
| 素材目录搬到 `assets/` | 与「取消 web 目录复制」是同一刀，分开做会两处改两遍 | P5 |
| `gl/config.py` 仍在 import 期解析路径并建目录 | 需要组合根先接管路径注入 | P3（bootstrap 装配） |
| `StateStorePort` 拆成 `LibraryStore` + `SettingsStore` | 现在两者共享同一写者，拆早了反而增加同步成本 | P3（服务拆分时按需拆） |

## Risks or tradeoffs

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 迁移只在首次启动发生 | 用户如果先开旧版 exe 又开新版，会出现两套写入 | 检测到 v1 与 v2 同时存在时以 v2 为准；旧文件会被搬进备份，不会覆盖 v2 |
| 去抖窗口内崩溃 | 最多丢最后一次窗口（≤500ms） | 会话与启动/结束这类关键点强制 flush；其余可重建 |
| 备份目录增长 | 每次迁移 + 每个文件每进程一次 pre-write 备份 | 每种前缀保留最近 3 份，自动清理 |

## Next

**P3 用例服务化 + 桥接 mixins**：把 `gl/api.py` 的 106 个方法按域拆进 `app/services` 与
`ui/bridge` mixins，用 `TaskRunner` 收掉散落线程，契约快照保持零漂移。
