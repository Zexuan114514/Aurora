# 插件与规则包（贡献者入口）

三种贡献方式，都不需要改核心代码：**资料源插件**、**翻译引擎插件**、**引擎规则包**。
契约细节见 [`architecture/contracts/plugin-api-v1.md`](architecture/contracts/plugin-api-v1.md)，
决策见 [ADR-0009](adr/ADR-0009-plugin-api-v1.md)（插件）与 [ADR-0008](adr/ADR-0008-declarative-engine-rules.md)（规则包）。

> ⚠️ **信任模型**：插件与 Aurora 同进程、以你的用户权限运行，能读文件、能联网。
> 宿主只保证「插件出错不会带崩 Aurora」，不保证「插件不做坏事」——只装你信任来源的插件。

## 1. 资料源插件

目录 `data/plugins/sources/<id>/`（目录名必须等于 manifest 里的 `id`），含 `plugin.json` + `main.py`。

```json
{
  "api_version": "1.0",
  "kind": "source",
  "id": "example",
  "name": "示例资料源",
  "version": "1.0.0",
  "entry": "main.py",
  "author": "你的名字",
  "homepage": "https://example.com",
  "permissions": ["network"],
  "settings": [
    { "key": "api_key", "label": "API Key", "type": "text", "default": "" }
  ]
}
```

```python
class Plugin:
    id = "example"
    name = "示例资料源"
    kind = "api"          # api = 可搜索 + 拉详情；link = 只给一条搜索链接
    supports_lang = True

    def bind_host(self, host):
        """可选：宿主注入上下文（设置 / 日志 / 带代理的 HTTP / 时钟）。"""
        self.host = host
        self.api_key = host.get("api_key", "")
        host.log("example 插件已就绪")

    def search(self, query, lang="schinese"):
        # 返回 [{source, source_id, name, score, thumb?}]；找不到就返回空列表
        return []

    def fetch(self, candidate, lang="schinese"):
        # 返回详情 dict；找不到返回 None
        return None
```

约定：`Candidate.source` / `Metadata.source` 必须等于插件 `id`；**不要用异常表示「没找到」**，
异常只留给真正的故障（宿主会计数，连续 3 次失败自动禁用该插件）。

## 2. 翻译引擎插件

目录 `data/plugins/translators/<id>/`，manifest 里 `kind` 填 `"translator"`。

```python
class Plugin:
    id = "example"
    name = "示例翻译"
    requires_key = True      # 没配 Key 时宿主只提示，不阻止
    supports_stream = True

    def translate(self, text, *, context, target, glossary, on_delta):
        # on_delta("片段") 可以边翻边回；返回 {"text": ..., "provider": "example"}
        return {"text": text, "provider": "example"}
```

约定：**不要自己缓存**（缓存归宿主）；不要修改传入的 `context` / `glossary`；
长耗时调用要尊重宿主超时。

## 3. 引擎规则包（实测 hook 码）

目录 `data/rules/engines/*.json`（同指纹时**覆盖内置**，并记一条诊断日志）。
内置包在 `aurora/rules/engines/`，由 `tools/export_engine_rules.py` 从
`aurora/domain/engine_rules.py` 导出，生成表见 [`engines.md`](engines.md) 末尾。

```json
{
  "schema": "aurora.engine-rules/1",
  "rules": [
    {
      "id": "my-engine-my-game-123456",
      "fingerprint": { "name": "game.exe", "size": 1992192, "crc32": "0x52EA5D63" },
      "engine": "MyEngine",
      "hook_code": { "mode": "Q", "offset": -4, "rva": "0xA22E", "module": "<exe>" },
      "text": { "encoding": "utf-16", "codepage": null },
      "profile": { "name_prefix": true, "collapse_doubling": true, "dedupe_window": 8.0 },
      "evidence": { "date": "2026-09-21", "game": "作品名",
                    "sample": "实测抓到的一句原文", "note": "怎么找到的 + 验证结论" }
    }
  ]
}
```

| 约束 | 说明 |
| --- | --- |
| 指纹 | 文件名 + 字节数 + CRC32 三者全等才启用（换版本不会误套地址） |
| `rva` | 只写模块内 RVA（`0x…`），**不要写绝对地址** |
| `profile` 白名单 | `name_prefix` / `collapse_doubling` / `dedupe_window` / `variant_settle` / `hook_hint` |
| `evidence` | 内置规则必填（date/game/sample）；用户规则可省，省了就标「未验证」 |
| 校验 | 加载时做 schema 校验；`tools/checks/check_engine_rules.py` 与 CI 用同一套 |

## 4. 复查与排错

| 想做的事 | 命令 / 位置 |
| --- | --- |
| 看插件状态与失败原因 | `Api.list_plugins()` / `Api.rescan_plugins()`（界面入口见 P6.3） |
| 校验规则包 | `python tools/checks/check_engine_rules.py` |
| 重新生成规则包与文档表 | `python tools/export_engine_rules.py --write` |
| 离线全量检查 | `python tools/checks/run_all.py` |
