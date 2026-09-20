# 数据 Schema v2 与迁移

## Summary

把单一 `data/library.json` 拆成**职责清晰、写入成本可控、可迁移可回滚**的四个真相文件：
`state/settings.json`、`state/library.json`、`state/sessions.jsonl`、`vntext/glossary.json`。
迁移单向 1 → 2，自动备份，支持干跑；v2 能读 v1，v1 不能读 v2（靠备份回退）。

## 目录布局

```
data/                           # AURORA_DATA → 程序目录 data/ → %LOCALAPPDATA%\aurora-launcher
  state/
    settings.json               # 用户设置（含 API Key），schema_version: 2
    library.json                # games + bookshelves，schema_version: 2
    sessions.jsonl              # 追加式会话记录（每行一条 JSON）
    backup/                     # 迁移与写入前备份，保留最近 3 份
  vntext/
    glossary.json               # 术语表：全局 + 每游戏
  rules/engines/*.json          # 用户引擎规则包（覆盖内置）
  plugins/{sources,translators}/<id>/{plugin.json,main.py}
  covers/ backgrounds/ icons/          # 用户与下载素材：P2 起仍在原位，P5 资产服务化时再搬到 assets/
  cache/sources/<source>/<hash>.json   # 接口缓存（可重建）
  cache/vntext/<hash>.json             # 译文缓存（可重建）
  logs/aurora.log*                     # 结构化日志（按大小/日期滚动）
  webview/                             # WebView2 / Qt 用户数据
  downloads/                           # 默认下载目录（可在设置里改）
```

与 v1 的差异：`data/library.json`（v1，单文件）→ `state/` 三件套；`data/glossary.json` → `vntext/glossary.json`；
`data/{covers,backgrounds,icons}` → `assets/`；`data/aurora.log` → `logs/aurora.log`；
新增 `rules/` 与 `plugins/`。

## 文件 schema

### `state/settings.json`

```json
{ "schema_version": 2, "settings": { "accent": "#0A84FF", "translate_api_key": "…" } }
```

现有 39 项设置按域分组（键名与 v1 保持一致，避免迁移期改名）：

| 域 | 键 |
| --- | --- |
| 外观 | `accent` `blur` `saturation` `scrim` `palette` `theme_mode` `hall_layout` `ken_burns` `show_playtime` `close_to_tray` |
| 资料源 | `lang` `sources` `auto_search` |
| 简介翻译 | `translate_enabled` `translate_provider` `translate_base_url` `translate_api_key` `translate_model` `translate_target` `show_original` |
| 网络 | `proxy_mode` `proxy_url` `proxy_fallback` |
| 转区 | `le_proc_path` `locale_default` |
| 获取游戏 | `download_dir` `download_watch` `download_extract` `download_baseline_dir` `download_seen` `resource_sites` |
| 游戏内翻译 | `vntext_enabled` `vntext_engine` `vntext_tractor_path` `vntext_auto_start` `vntext_context_lines` `vntext_max_chars` `vntext_ocr_interval` `vntext_overlay` |
| v2 新增 | `plugins`（插件配置）、`ui`（界面偏好；localStorage 只作为缓存） |

密钥策略：仍存明文（单机桌面程序，靠 Windows 用户目录权限兜底）；**导出库文件默认剥离**；
日志与诊断包对 `*_key` / `*token*` 字段脱敏。DPAPI 加密作为后续可选项，不在 v2 范围。

### `state/library.json`

```json
{ "schema_version": 2,
  "games": [ { "id": "…", "exe": "…", "play_time": 0 } ],
  "bookshelves": [ { "id": "…", "name": "…", "created_at": 0 } ] }
```

游戏记录字段（当前 60 个，v2 保持一致并允许新增）：

| 组 | 字段 |
| --- | --- |
| 标识 | `id` `exe` `exe_stem` `dir_name` |
| 展示名 | `name` `name_cn` `name_original` `steam_name` |
| 来源与匹配 | `appid` `data_source` `source_id` `source_url` `store_url` `query_used` `queries` `strong_queries` `match_score` `match_source` `metadata_state` `metadata_note` |
| 简介 | `description` `description_original` `description_translated` `description_lang` `about` |
| 分类信息 | `developers` `publishers` `genres` `categories` `release_date` `rating` `metacritic` `website` |
| 图片 | `cover` `cover_sources` `custom_cover` `custom_icon` `logo` `header_image` `images` |
| 背景与视图 | `background` `background_kind` `bg_scale` `bg_x` `bg_y` |
| 会话聚合 | `play_time` `play_count` `last_played` `sessions`（保留最近若干条，兼容导入/导出） |
| 会话进行态 | `play_started_at` `play_pid` `play_launcher_pid` `play_heartbeat` |
| 组织 | `bookshelf_ids` `status` `favorite` `added_at` |
| 本机配置 | `launch_args` `locale_enabled` `locale_guid` `vntext_ocr_region` |
| 按需新增 | `vntext_hook`（用户为单个游戏保存的专用 hook 码，仅在设置过时出现） |

约定：未知字段必须在读写时**原样保留**（前向兼容）；`sessions` 在 v2 中作为历史摘要保留，
完整历史以 `state/sessions.jsonl` 为准。

### `state/sessions.jsonl`

```json
{"game_id":"a1b2c3d4e5f6","ts_start":1758326400,"ts_end":1758329400,"seconds":3000,"source":"session"}
```

`source` 取值：`session`（实时会话）| `migrated-v1`（从 v1 内嵌历史摊平而来）。

| 规则 | 说明 |
| --- | --- |
| 追加写 | 会话结束时追加一行并立即 flush；崩溃最多丢最后一条 |
| 结算口径 | `seconds = 本体真正消失时刻 − 起始时刻`（与现有实现一致） |
| 轮转 | 单文件 > 2 MB 时改名为 `sessions-<YYYYMM>.jsonl`，只保留最近 12 个文件 |
| 真相归属 | 聚合值（`play_time` / `play_count`）在 `library.json`；jsonl 用于历史与审计 |

### `vntext/glossary.json`

```json
{ "schema_version": 2, "global": { "原文": "译文" }, "games": { "<game_id>": { "原文": "译文" } } }
```

### 规则与插件

见 [`plugin-api-v1.md`](plugin-api-v1.md)：`rules/engines/*.json` 与 `plugins/**`。

## 迁移 1 → 2

| 步骤 | 行为 | 失败处理 |
| --- | --- | --- |
| 1 检测 | 存在 `data/library.json` 且无 `state/settings.json` → 判定为 v1 | 都不是 → 视为全新安装，写空 v2 |
| 2 校验 | 解析 v1 JSON，校验 `games` 为数组、`bookshelves` / `settings` 形状正确 | 解析失败 → 尝试 `data/library.json.bak`；仍失败 → 报错并保留原文件 |
| 3 备份 | 复制到 `state/backup/library-v1-<ts>.json` 并记录校验和 | 备份失败 → 中止迁移（不写任何新文件） |
| 4 拆分 | `settings` → `state/settings.json`；`games` + `bookshelves` → `state/library.json`；各 game 的 `sessions` → `state/sessions.jsonl` | 单条记录形状异常 → 保留原字段并记日志（不丢数据） |
| 5 测试写 | 写 `*.tmp` 后校验可解析、记录数与字段数一致 | 不一致 → 中止并删除 tmp |
| 6 提交 | 原子替换到位（`os.replace`） | 任一步失败 → 保留 v1 文件不动 |
| 7 收尾 | 把 v1 文件移入 `state/backup/`（不在原位置留第二份真相），写迁移日志 | —— |

**干跑模式**（P2 已实现）：`Aurora.exe --check-migration`（源码 `python main.py --check-migration`）只输出
「将迁移多少游戏 / 多少会话 / 多少设置键 / 备份路径」，不写任何文件；v1 不可解析时退出码 2 并给出原因。

**回滚**：关闭 Aurora → 把 `state/backup/library-v1-<ts>.json` 复制回 `data/library.json` →
删除（或改名保留）`data/state/` → 用旧版 exe 启动。界面提示与文档都要给出这三步。

**降级保护**：v2 程序读 v1 会先迁移；v1 程序读 v2 会因找不到 `data/library.json` 而起空库 ——
因此迁移时必须保留可恢复的备份，并在完成后提示用户「已升级数据格式，旧版本需用备份回退」。

## 写入与并发

| 规则 | 说明 |
| --- | --- |
| 单写者 | 所有对 `state/*` 的写入都经同一个写者（`infra/store`），禁止其它模块直接写文件 |
| 原子写 | 写 `*.tmp` → flush + `os.fsync` → `os.replace`；关键文件替换后回读校验（大小 + 可解析） |
| 去抖 | `settings.json` 500ms、`library.json` 300ms；会话结束、游戏启动/结束、退出前**立即 flush** |
| 部分更新 | 设置与库分文件后，单次设置修改只重写 `settings.json`（常量级），不再重写全部游戏 |
| 崩溃一致性 | 退出前 flush；强杀最多丢最后一次去抖窗口（≤500ms） |
| 损坏恢复 | 解析失败 → 用 `state/backup/` 最近可用备份；原文件改名 `*.corrupt-<ts>` 保留 |
| 并发读 | 读走内存快照，不直接读文件，避免读到半写状态 |

## 导出 / 导入

| 项 | v2 行为 |
| --- | --- |
| 导出内容 | `app` / `version` / `schema_version: 2` / `exported_at` / `games` / `bookshelves` / `settings`（**剥离密钥**） |
| 导出文件名 | `aurora-library.json` |
| 导入 v2 | 按 `exe` 路径去重合并；分类按名字合并；不覆盖已有条目 |
| 导入 v1 | **继续兼容**：无 `schema_version` 或 `schema_version: 1` 时按同样规则合并 |
| 导入失败 | 返回 `bad-file` / `cancelled`，不做部分写入 |

## 兼容规则

| 变更 | 兼容性 | 要求 |
| --- | --- | --- |
| 新增可选字段 | 兼容 | 读写保留未知字段；迁移器不删字段 |
| 字段改名 | **破坏性** | 需要迁移步骤 + ADR；迁移器负责映射 |
| 拆分 / 合并文件 | **破坏性** | 需要迁移器 + 备份 + 回滚说明 |
| 新增 `schema_version` | 兼容 | 旧版本会因找不到文件而起空库（回滚步骤已在本文档给出） |

## 验证

- 单测：迁移器（真实去敏库夹具：24 游戏 / 60 字段 / 39 设置）、字段全等断言、干跑不写文件、
  备份校验和、损坏文件恢复、去抖合并、会话追加与轮转。
- 集成：迁移 → 启动 → 导入 → 启动游戏 → 结束 → 时长记账 → 导出 → 在新目录导入。
- 安全：导出文件与诊断包中不出现 `translate_api_key` 的值。
