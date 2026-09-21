# 插件 API v1 与引擎规则包契约

## Summary

把「社区能贡献什么」限制在三个声明式入口：**资料源插件**、**翻译引擎插件**、**引擎规则包**。
三者都不需要改核心代码；宿主对插件做 `api_version` 门禁与逐次调用的异常隔离，但**不提供沙箱**。

## 目标与非目标

| 目标 | 非目标 |
| --- | --- |
| 加一个资料源 / 翻译引擎只需一个目录 + 一份 manifest | 不做远程插件市场与自动安装 |
| 引擎实测结论（指纹、hook 码、清洗档位）可声明式贡献 | 不做进程隔离或权限沙箱（插件与宿主同权限） |
| 插件出错不影响宿主启动与其它插件 | 不允许插件替换核心清洗规则或桥接方法 |
| 用户本地规则优先于内置规则，且可追溯来源 | 不做规则的热重载（需显式重载动作） |

## 目录与发现

```
data/
  plugins/
    sources/<id>/plugin.json + main.py (+ 可选的辅助文件)
    translators/<id>/plugin.json + main.py
  rules/
    engines/*.json                用户规则包（覆盖内置）
aurora/rules/engines/*.json       内置规则包（随程序分发）
```

| 项 | 规则 |
| --- | --- |
| 发现时机 | 启动时扫描一次；用户点「重新扫描插件」时再扫 |
| 加载方式 | `importlib.util.spec_from_file_location`，模块名 `aurora_plugin_<kind>_<id>`，**不修改 `sys.path`** |
| 目录名 | 必须等于 manifest 的 `id` |
| 冲突 | 同 `kind` 下 `id` 重复 → 后扫描到的拒绝加载并记录 |
| 失败 | 单个插件加载失败只影响它自己；界面展示插件状态与原因 |

## manifest（`plugin.json`）

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `api_version` | string | 是 | 形如 `"1.0"`；主版本必须与宿主一致，次版本不得高于宿主 |
| `kind` | string | 是 | `source` 或 `translator` |
| `id` | string | 是 | `[a-z0-9_-]{3,32}`，与目录名一致 |
| `name` | string | 是 | 界面显示名 |
| `version` | string | 是 | 插件自身版本（semver） |
| `entry` | string | 是 | 入口文件，默认 `main.py` |
| `class` | string | 否 | 入口类名；缺省时取入口模块里第一个满足协议的子类 |
| `author` / `homepage` / `description` | string | 否 | 展示与溯源 |
| `permissions` | string[] | 否 | 自述用途：`network` / `files:read` / `files:write` / `process`，界面展示（**不是**强制拦截） |
| `settings` | object[] | 否 | 插件配置项 schema，由宿主渲染到设置页并持久化在 `settings.json` 的 `plugins.<id>` 下 |
| `min_app` | string | 否 | 最低 Aurora 版本 |

## 生命周期与错误隔离

| 阶段 | 行为 | 失败处理 |
| --- | --- | --- |
| 发现 | 扫描目录、读 manifest | 记录并跳过 |
| 校验 | manifest schema + `api_version` + id 合法性 | 拒绝加载，状态 = `incompatible` |
| 导入 | 按 `entry` 加载模块 | 状态 = `load-error`，附异常摘要 |
| 实例化 | 找入口类、注入 `HostContext`（设置、日志、HTTP 客户端、Clock） | 状态 = `init-error` |
| 注册 | 加入 `MetadataSource[]` / `Translator[]` | —— |
| 调用 | 每次调用包裹 try/except + 超时 | 返回错误结果 + 计数；连续 3 次失败 → 自动禁用 |
| 卸载 | 用户显式禁用/重载 | 从注册表移除；不保证能回收其线程 |

**明确声明**：插件在宿主进程内、以用户权限运行，可以访问网络与文件。宿主只能保证「不因插件异常而崩溃」，
不能保证「插件不做坏事」。设置页与本文档都如实说明。

## 资料源插件骨架

```python
# data/plugins/sources/example/main.py
from aurora.domain.contracts import Candidate, Metadata

class Plugin:
    id = "example"
    name = "示例资料源"
    kind = "api"           # api = 可搜索 + 拉详情；link = 只给搜索链接
    homepage = "https://example.com"
    supports_lang = True   # fetch 时会收到 lang 参数
    search_url = "https://example.com/search?q={query}"   # kind=link 时使用

    def search(self, query: str, lang: str = "schinese") -> list[Candidate]:
        ...

    def fetch(self, candidate: Candidate, lang: str = "schinese") -> Metadata | None:
        ...
```

约定：`Candidate.source` / `Metadata.source` 必须等于插件 `id`；返回空列表或 `None` 表示无结果，
不要用异常表示「未找到」；异常只用于真正的故障。

## 翻译引擎插件骨架

```python
# data/plugins/translators/example/main.py
class Plugin:
    id = "example"
    name = "示例翻译"
    requires_key = True          # 未配置 API Key 时宿主提示但不阻止
    supports_stream = True       # 支持逐字返回

    def translate(self, text: str, *, context: list[str], target: str,
                  glossary: dict[str, str], on_delta) -> dict:
        # on_delta(piece: str) 逐片回调；返回 {"text": ..., "provider": "example"}
        ...
```

约定：不得自行做缓存（缓存归宿主）；不得修改传入的 `context` / `glossary`；
必须尊重超时（宿主会中断长时间无输出的调用）。

## 引擎规则包（`data/rules/engines/*.json`）

```json
{
  "schema": "aurora.engine-rules/1",
  "rules": [
    {
      "id": "willplus-advhd-crack-1992192",
      "fingerprint": { "name": "advhd_crack.exe", "size": 1992192, "crc32": "0x52EA5D63" },
      "engine": "WillPlus",
      "hook_code": { "mode": "Q", "offset": -4, "rva": "0xA22E", "module": "<exe>" },
      "text": { "encoding": "utf-16", "codepage": null },
      "profile": { "name_prefix": true, "collapse_doubling": true,
                   "dedupe_window": 8.0, "variant_settle": 0.55 },
      "evidence": {
        "date": "2026-09-19",
        "game": "少女之剑与秘密的协奏曲",
        "sample": "１０年以上前の、初恋のことを。",
        "note": "Textractor 自带 WillPlus 系钩子全部失配（含算到 igc32.dll 的乱码回显）；该地址实测可用"
      }
    },
    {
      "id": "artemis-amakano3-5170176",
      "fingerprint": { "name": "amakano3.exe", "size": 5170176, "crc32": "0xA1FF529B" },
      "engine": "Artemis/Emote",
      "hook_code": { "mode": "S", "offset": -108, "rva": "0x1B1F70", "module": "<exe>" },
      "text": { "encoding": "utf-8", "codepage": 65001 },
      "profile": { "name_prefix": true, "collapse_doubling": true, "dedupe_window": 8.0 },
      "evidence": {
        "date": "2026-09-19",
        "game": "アマカノ３（甜蜜女友 3）",
        "sample": "明らかに、詩夢の顔が青い。",
        "note": "引擎用 D3D11 自绘文字，GDI 钩子全空；地址经 MisakaHookFinder 文本搜索得到"
      }
    }
  ]
}
```

| 约束 | 规则 |
| --- | --- |
| 指纹 | `name` + `size` + `crc32` 三者必须同时匹配才启用 |
| hook 码模式 | `S`=字节串、`Q`=UTF-16、`V`=UTF-8，另有 `A/B/W/H/M` 变体 |
| `rva` | 相对模块基址（写成 `0x…`），不得写绝对地址，避免换机失效 |
| `profile` 白名单 | `name_prefix`、`collapse_doubling`、`dedupe_window`、`variant_settle`、`hook_hint` |
| `evidence` | 内置规则必填（date/game/sample）；用户规则可省略，省略时标记为「未验证」 |
| 优先级 | 内置规则包 → 用户规则包（同指纹时用户覆盖，并写一条诊断日志） |
| 校验时机 | 加载时做 schema 校验；CI 用同一套 schema 校验内置规则 |

## 宿主实现状态（P6.4 起）

| 契约部分 | 落地位置 | 状态 |
| --- | --- | --- |
| 资料源插件 → 宿主 `Source` | `gl/sources/plugin_source.py` + `SourceManager.plugin_sources()` | ✅ P6.3：参与搜索 / 详情 / `describe()`，只有 `state == ok` 的插件生效 |
| 翻译引擎插件 → 简介翻译 | `aurora/app/services/translators.py` + `gl/translate.py` 的 `plugin_translate` | ✅ P6.4：`translate_provider = plugin:<id>`，显式选择不静默换引擎 |
| 翻译引擎插件 → 游戏内逐句翻译 | 同上 + `aurora/infra/linetrans.py` 的 `plugin_getter` | ✅ P6.4：带 `context` / `glossary` / `on_delta`；插件失败落回 LLM / 免费兜底 |
| 引擎规则包（内置 + 用户覆盖） | `aurora/infra/rules.py` + `aurora/rules/engines/*.json` | ✅ P6.1：schema 校验、同指纹用户覆盖并记日志 |
| 状态 / 权限 / 来源的界面呈现 | 设置页「插件」页签（`gl/web/app/views/settings.js`） | ✅ P6.4：中文状态、失败原因、权限自述、来源路径、「重新扫描插件」 |
| `settings` schema → 宿主渲染与持久化 | —— | ⏳ 未实现：manifest 里的 `settings` 目前只在状态里携带，表单与 `settings.json` 的 `plugins.<id>` 持久化留给后续阶段 |
| 调用超时强制中断 | —— | ⏳ 未实现：只有 `CallGuard` 计数与三连失败自动禁用，插件自己负责超时 |

## 文档生成

`docs/engines.md` 的「已通过测试」表格由内置规则包生成（一条规则一行：引擎 / 作品 / 结论 / 备注），
避免「文档里写了、代码里没带」的两份真相。手写的实测叙事仍保留在文档其它小节。

## 兼容与演进

| 变更 | 处理 |
| --- | --- |
| 新增可选 manifest 字段 / 新增协议方法 | 次版本号 +1，向后兼容 |
| 修改已有方法签名 / 语义 | 主版本号 +1；旧插件标记 `incompatible` 并在界面提示 |
| 移除协议 | 至少保留一个大版本，并给出替代写法 |

## 验证

- 单测：manifest 校验（各类非法值）、api_version 门禁、异常隔离与自动禁用、规则 schema 校验、覆盖优先级。
- 集成：用 fake 插件跑一遍「发现 → 注册 → 搜索/翻译 → 失败 → 禁用」。
- CI：内置规则包全部通过 schema 校验；`docs/engines.md` 生成结果与仓库内容一致（无 diff）。
