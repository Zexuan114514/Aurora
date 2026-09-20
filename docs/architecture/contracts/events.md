# 事件契约（后端 → 前端）

## Summary

后端与前端之间只有一条推送通道：**事件信封**。所有主题名与载荷字段在本文件冻结；改名等同破坏性变更。
当前共 14 个主题（见 `bridge-contract.json` 的 `events` 字段）。

## 信封格式

```json
{
  "topic": "vntext:line",
  "seq": 1024,
  "ts": 1758326400,
  "payload": { "phase": "translated", "text": "……", "translation": "……", "provider": "llm" }
}
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `topic` | string | `命名空间:动作`；命名空间取 `vntext / metadata / game / games / hooksearch / downloads / batch / translate` |
| `seq` | int | 进程内单调递增，用于前端丢弃乱序与重复 |
| `ts` | int | unix 秒（注入 Clock，便于测试） |
| `payload` | object | 每个主题一个形状；不允许 `null` |

投递方式：后端把整个信封序列化为**单个 JSON 字符串**，通过渲染层的统一分发函数送达前端
（当前实现是 `window.__aurora.emit(topic, payload)`；目标实现是 `window.__aurora.dispatch(envelopeJson)`）。
禁止用字符串拼接构造 payload。

## 主题表

| 主题 | 触发 | 载荷要点 | 前端反应 |
| --- | --- | --- | --- |
| `vntext:line` | 文本源出句 / 译文完成 / 失败 | `phase = source \| translated \| error`；`text`、`translation`、`provider`、`error` | 更新翻译面板与悬浮窗 |
| `vntext:status` | 文本会话状态变化（启动/停止/锁定线程/切换穿透/暂停） | 与 `get_vntext_status()` 同形状 | 刷新面板胶囊与线程列表 |
| `hooksearch:status` | 钩子查找进度 | `phase`、`message`、`candidates`、`code`、`steps` | 刷新查找器面板 |
| `metadata:searching` | 开始匹配某游戏 | `game_id`、`query` | 封面外圈呼吸动画 |
| `metadata:error` | 匹配失败 | `game_id`、`reason`（`network` / `no-results` / `low-confidence` / `no-query`）、`note` | 展示提示并允许手动匹配 |
| `metadata:notfound` | 全部源无结果 | `game_id`、`query` | 提示"没找到"并保留占位 |
| `game:updated` | 单游戏记录变化（封面/背景/名称/状态等） | `game`（PublicGame） | 增量更新该卡片 |
| `games:imported` | 批量导入完成 | `games[]`、`ids[]`、`ignored` | 插入卡片并聚焦第一条 |
| `game:running` | 会话开始（含重新接管） | `game_id`、`pid`、`started_at` | 显示运行中徽标与计时 |
| `game:stopped` | 会话结束 | `game_id`、`seconds`、`play_time`、`play_count` | 结算时长、撤销运行中状态 |
| `translate:done` | 简介翻译完成 | `game_id`、`description_translated`、`provider` | 更新简介与"显示原文/译文" |
| `batch:progress` | 批量任务进度（重抓全部/翻译全部） | `kind`、`done`、`total` | 设置页进度文本 |
| `batch:done` | 批量任务结束 | `kind`、`done`、`total`、`ok` | 收尾提示 |
| `downloads:status` | 下载目录监听状态（发现/解压/导入） | `phase`、`name`、`message` | 「获取游戏」面板状态行 |

## 顺序、合并与背压

1. **顺序**：同一主题内必须按 `seq` 递增到达；前端丢弃 `seq` 小于已处理值的信封。
2. **合并**：高频主题（`vntext:line` 的 `delta` 类更新）在 UI 线程侧以 100ms 窗口合并；
   `start` 与 `done` 不合并（保证首字与收尾及时）。
3. **背压**：合并队列上限 500 条；超限时丢弃最旧的中间态，只保留最新态（丢中间态不丢完成态）。
4. **窗口无关**：窗口已销毁时事件直接丢弃，不写错误日志（避免退出时日志噪声）。
5. **跨线程**：任何后台线程都不得直接调用渲染层；一律经事件总线 → UI 线程队列 → 分发。

## 兼容规则

| 变更 | 兼容性 | 要求 |
| --- | --- | --- |
| 新增主题 | 兼容 | 前端忽略未知主题即可；更新本文件与快照 |
| 新增载荷字段 | 兼容 | 前端必须容忍缺省（用默认值） |
| 删除/改名主题或字段 | **破坏性** | 需要 ADR + 前端同步迁移 + 快照更新 |
| 语义变化（同名字段不同含义） | **破坏性** | 同上，且必须新增字段而不是复用 |

## 验证

- 契约快照：`contracts/bridge-contract.json` 中的 `events` 与 `event_envelope`。
- 单测：信封字段完整、`seq` 单调、合并窗口行为、窗口销毁时静默丢弃。
- 真机：`tools/e2e.py` 观察运行中徽标、导入、翻译面板、下载面板的状态流转。
