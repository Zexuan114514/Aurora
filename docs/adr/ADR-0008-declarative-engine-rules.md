# ADR-0008：引擎规则与 hook 码声明式 JSON 化

## 状态

已接受。

## 背景

引擎相关的实测结论目前散落在三处：`gl/vntext.py` 的 `ENGINE_PROFILES`（引擎清洗档位）与
`WILLPLUS_AUTO_HOOKS`（指纹 → hook 码，含两套 U 实测数据：WillPlus/AdvHD 与 Artemis/Emote）、
`docs/engines.md` 的人工表格、README 的长篇叙事。三份真相会漂移；贡献一条实测规则需要读懂 1900 行代码。

## 决策驱动

- 社区贡献门槛：一条实测结论应该是一个 JSON 对象，而不是一次代码读懂 + 改动。
- 可追溯：每条规则要带证据（日期、作品、样例、备注）。
- 可回归：规则参与离线校验与真机验收。

## 考虑过的选项

1. **保持 Python 常量**（现状）。
2. **声明式 JSON 规则包**：`data/rules/engines/*.json` + 内置包随程序分发。
3. **外部数据库/在线规则库**：与「单机免安装、离线可用」冲突。

## 决定

选择 **2**。规则 schema 见 `contracts/plugin-api-v1.md`：指纹为「exe 文件名 + 字节数 + CRC32」三元组，
hook 码只写模块内 RVA（不写绝对地址），`profile` 有白名单键，内置规则必须有 `evidence`；
用户规则同指纹覆盖内置并记录日志。`docs/engines.md` 的实测表格由规则包生成。

## 后果

- ✅ 贡献者只写 JSON；文档与代码同源；规则可被 CI 校验（schema + hook 码格式 + 指纹唯一性）。
- ✅ 现有两条实测码（`HQ-4@A22E:AdvHD_crack.exe`、`HS65001#-1B1F70:Amakano3.exe`）可机械迁移，不手抄。
- ⚠️ 需要一次性把常量导出成 JSON，并保留旧常量作为过渡（比对一致后再删）。
- ⚠️ 规则包是可信输入：非法规则要拒绝加载而不是崩溃；用户规则一律走 schema 校验。

## 后续动作

- P6 写导出脚本：从现有常量生成内置规则包，并用单测断言两者等价。
- 真机验收：WillPlus/Artemis 两款游戏开翻译后自动带出 hook 码，`vntext_live.py` 通过。
