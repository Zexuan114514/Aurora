# P7 治理收口（交付记录）

P7 的目标是**让边界与契约长期不腐化**：CI 全量、诊断包、README 与开发文档同步。
前六阶段把结构做完，这一阶段把「怎么保证它不烂」钉下来。

## 1. CI 全量（单元 / 契约 / 迁移 / 守卫 / 打包 dry-run）

`.github/workflows/offline-checks.yml`（windows-latest，`PYTHONUTF8=1`）现在的步骤与对应覆盖：

| 步骤 | 覆盖 | 失败会怎样 |
| --- | --- | --- |
| `python tools\checks\run_all.py --json checks-result.json` | 契约快照 / 依赖白名单 / 去敏夹具 / 探针清单 / 架构基线 / 桥接转发目标 / 引擎规则包 / 分层守卫 / 打包清单 / 启动冒烟（10 项） | 任一项红 → 作业失败，结果 JSON 照常上传 |
| `python tools\build_exe.py --dry-run` | 打包输入：前端清单与模块树、图标、内置规则包、动态声明的 winrt 模块（**P7 新增**） | 缺件即失败，不用等 3 分钟 PyInstaller |
| `python -m pytest` | 单元 + domain 金样本 + 桥接接线 + 插件 + 诊断包 | 任一条失败 |
| `python -m pytest tests\test_state_store.py -q` | **迁移专项**：v1→v2 全等 / 干跑不写文件 / 二次加载不再迁移 / 去抖 / 损坏恢复 / 导出脱敏 / 导入合并 / 回滚 | 单独一步，红在哪一眼看得出 |
| `python tools\collect_diagnostics.py --out diagnostics-ci.zip` | 诊断包在干净 checkout 上也能生成（**P7 新增**） | 生成失败即失败 |
| `upload-artifact` | `checks-result.json` + `diagnostics-ci.zip` | —— |

`build_exe.py --dry-run` 本地输出（P7 实测）：

```
打包输入检查通过（dry-run，未调用 PyInstaller）：
  前端：4 个顶层文件 + 18 个模块文件
  图标：gl\assets\aurora.ico
  规则包：aurora/rules/engines（1 个）
  动态声明：winrt 7 个模块 + webview 两个平台后端
```

## 2. 诊断包

「出问题了怎么办」在 P7 之前没有答案：用户要自己找日志、抄版本、描述插件状态。现在一条命令 / 一个按钮：

| 入口 | 说明 |
| --- | --- |
| 界面：设置 → 关于 → **导出诊断包…** | 桥接方法 `export_diagnostics()`；导出后在页面显示完整路径并给 toast |
| 命令行：`python tools\collect_diagnostics.py [--out 路径] [--json]` | 不打界面；CI 也用它（`diagnose` 类脚本） |
| 服务：`aurora/app/services/diagnostics.py` | 两个入口共用同一实现，`DiagnosticsService.build()` |

zip 内容（一层同名目录）：

| 文件 | 内容 |
| --- | --- |
| `README.txt` | 里面是什么、隐私怎么处理、怎么发给维护者 |
| `summary.json` | 版本 / Python / 系统 / 是否 frozen / 数据目录计数 / 磁盘余量 / **迁移计划（干跑）** / 插件状态 / 资料源状态 |
| `settings.json` | 设置快照，**脱敏**：字段名含 key/token/secret/password/cookie/credential 的值打码为 `***`，URL 里的 `user:pass@` 抹成 `***@` |
| `logs/*.log` | 日志尾部（每文件最多 256 KB、最多 5 个），被截断时在开头写一行说明 |

**不收集**：游戏可执行文件、素材原图、游戏库全文（那属于「导出游戏库」，不是排错）。
生成动作只读数据目录、只写目标 zip，不打网络。

实测（真机探针 `_sandbox/p7_diagnostics_probe.py`，PASS）：

```
关于页: {"pane":"about","hasButton":true,...}
导出后: {"hint":"已导出（2.3 KB）：…\\p7-data\\diagnostics\\Aurora-diagnostics-20260921-184521.zip",
         "toast":"诊断包已导出，出问题时把这个 zip 发给维护者","errors":[]}
条目: [README.txt, summary.json, settings.json]
```

## 3. 「故意违规能让 CI 变红」的证据

CI 全量只有在**真的会红**时才有意义。P7 当场做了两次故意违规（改坏 → 跑 → 还原，日志留档）：

| 违规 | 改法 | 守卫输出（留档） |
| --- | --- | --- |
| 契约漂移 | 在 `gl/web/app/core/panels.js` 里加一行 `call("no_such_bridge_method")` | `[FAIL] 契约快照（桥接 + 事件）`：`前端调用点与快照不一致：新增调用 ['no_such_bridge_method']`、`前端调用了后端不存在的方法`；`合计 10 项检查：通过 9，失败 1`（`_sandbox/p7-violation-contract.log`） |
| 分层越界 | 在 `aurora/ui/bridge/settings.py` 加 `from aurora.infra import config` | `[FAIL] 分层守卫`：`aurora/ui/bridge/settings.py 桥接层不得直接 import infra（改用 app 端口）`；同样 9/10（`_sandbox/p7-violation-layers.log`） |

两次都还原后复跑：`合计 10 项检查：通过 10，失败 0`。
（`_sandbox/` 是 gitignore 的本地目录，日志留在开发机上；CI 现场会把这些失败直接挂在作业日志里。）

## 4. README 与开发文档同步

| 文件 | 改了什么 |
| --- | --- |
| `README.md` | 目录结构补 `aurora/` 分层与 `data/plugins|rules`、前端模块树；自检脚本表补 `collect_diagnostics.py`、`build_exe.py --dry-run`、`run_all.py` 十项说明；「当前结果」表全部换成 P7 实测数字；新增「插件与规则包」「诊断包」两节 |
| `docs/architecture/13-roadmap.md` | 阶段总览与 P6/P7 状态行收口；真机矩阵的 `e2e.py` 期望值 90/90 → 94/94 |
| `docs/architecture/README.md` | 产物索引补 `p7-governance.md`；现状基线表里 P4/P5/P6/P7 的条目改成「已完成 + 证据」 |
| `tools/checks/tools-manifest.json` | 新增 `tools/collect_diagnostics.py`（`diagnose`/P7）；`build_exe.py` 与 `e2e.py` 的 expected 更新 |

## 5. 验收

| 项 | 结果 |
| --- | --- |
| `run_all` | **10/10** |
| `pytest` | **87 passed**（新增 `tests/test_diagnostics.py` 5 条：脱敏、zip 内容与计数、日志截断、可选项缺失、目标不可写） |
| `e2e` | **95/95（0 skipped）**（新增「关于页能导出诊断包（zip 落盘 + 页面显示路径）」） |
| `visual` | `errors=[]`，ring 判据与 P4.3-j 基线逐项一致 |
| 真机探针 | `_sandbox/p7_diagnostics_probe.py` PASS（按钮 → 导出 → zip 内容 → 无非预期 JS 错误） |
| CI 红/绿 | 故意违规两次都红（见上表），还原后绿；`build_exe.py --dry-run` 与 `collect_diagnostics.py` 在 CI 步骤里 |
| 契约 | 桥接方法 150 → **151**（`export_diagnostics`），前端调用点 99 → **100** |

## 6. 这一阶段**没有**做的事（如实登记）

1. **打包 dry-run 不验证真机启动**：exe 的实际构建与冷启动仍在本地跑（CI 的 windows-latest 装 PyInstaller + 打包要数分钟，暂无必要）。发布前仍按路线图「固定动作 4」人工对比体积与冷启动。
2. **诊断包不含性能采样**：没有 CPU/内存曲线，只有计数与磁盘余量；够排「状态不对」，不够排「卡顿」。真卡顿还是靠 `tools/snap.py` / 任务管理器。
3. **CI 不跑真机矩阵**：`e2e` / `visual` / `vntext_live` 需要真实游戏与窗口，仍在开发机上人工跑（这是 P0 就定下的边界）。
4. **README 数字仍是人工同步**：没有「README 与实测数字一致」的守卫。真正的数字源在 `tools/checks/baseline.json` 的 `history` 与各报告 JSON；README 只保证「写的是最近一次实测」。

## 7. 复核补丁（2026-09-21）：P2 之后的探针路径漂移 + 控制台编码

P7 收口当天做了一次「按 README 逐条跑一遍」的复核，结果发现**治理的盲区不在守卫本身，
而在没人执行的期望**：`tools/checks/tools-manifest.json` 里写着每个脚本「应该通过」，
但清单检查只校验字段是否填了，**从不真跑**，于是三类问题同时存在。

| # | 现象（实测） | 真因 | 修法 |
| --- | --- | --- | --- |
| 1 | `tools/check_library.py` / `vntext_live.py` / `vntext_hookprobe.py` / `vntext_rawdump.py` 开箱即 `FileNotFoundError: data\library.json` | P2 把库搬到 `state/`，四个脚本还在拼 v1 路径 | 统一走 `tools/_common.layout()`（`library_file()` / `settings_file()` / `load_library()`） |
| 2 | `check_fixture` 的「实时库比夹具多了字段」告警、架构基线的「实时库 N 游戏」计数**静默消失** | 两处都是 `if live.exists():` 且盯着 v1 路径 —— 迁移后条件恒为假 | 改盯 `data/state/library.json`；只有 v1 时明确 warn；都没有（CI）记一行说明 |
| 3 | `python tools/e2e.py` 裸跑在第 81 步崩：`UnicodeEncodeError: 'gbk' codec can't encode '\u22ef'`，报告停在 80/81（README 写的是 95/95） | 翻译面板状态行里有「⋯ → 转区启动…」，中文控制台 cp936 打不出来；CI 设了 `PYTHONUTF8=1` 所以只有本地中招 | 新增 `tools/_common.setup_console()`（只放宽 `errors`，不把 cp936 强改成 UTF-8 —— 那样中文会全屏乱码），**每个**探针脚本开头调用；守卫强制 |
| 4 | `tools/check_bridge.py` 恒假红（`exit 1`，报「后端缺失 apply_window_icon, refresh_running」） | 它只正则扫 `gl/web/app.js` + `gl/api.py`，P3/P4 之后两者都是薄壳 | 重写成复用 `tools/checks/common.py` 的解析：前端扫 `gl/web/app/**/*.js` + 悬浮窗 8 个动作，后端扫整个桥接 mixin 树 |
| 5 | 真机自测里 `モードのオーバーレイをデバイスがサポートしていません。`（D3D 覆盖模式提示）被当台词翻译 | 它有假名、有句号，形态上像台词 | `text_rules.looks_like_system_notice()`：**技术口吻 + 技术主语同时出现**才算噪声（单独「デバイスって何？」不误伤），并加 `tests/test_system_notice.py` |
| 6 | 每跑一次探针，工作区就有 16 个 `*-report.txt` 变脏 | 报告文件被跟踪，却又每次都重写 | `git rm --cached` + `.gitignore` 加 `tools/*-report.txt`；`.codex/`（本地技能包）一并忽略 |

### 守卫升级：清单从「元数据」变成「守卫」

`tools/checks/check_tools_manifest.py` 现在四件事一起做：

1. 登记完整（每个 `tools/*.py` 都在清单里，kind / phase / expected 合法）；
2. **控制台守卫**：每个脚本都要接 `tools/_common.setup_console()`；
3. **路径漂移守卫**：解析 AST，不许再出现 `ROOT / "data" / "library.json"` 这类 v1 路径
   （只看代码，文档字符串里的说明不算）；
4. **真跑 `kind=offline` 的三个脚本**（`check_bridge` / `check_library` / `meta_offline`），
   退出码非 0 即失败。

### 「故意违规会变红」的证据（本轮新增）

加一个临时脚本 `tools/zz_violation_probe.py`（不接 `setup_console`、自己拼 v1 路径、不登记清单）后：

```
$ python tools\checks\run_all.py          # 日志留档 _sandbox/p7b-violation-tools.log
[FAIL] 探针脚本清单
  x 新增脚本没有登记到清单：tools/zz_violation_probe.py
  x 这些脚本没接 tools/_common.setup_console()（中文控制台会崩）：zz_violation_probe.py
  x 这些脚本仍写死 v1 数据路径（P2 之后库在 data/state/ 下）：zz_violation_probe.py
== 合计 10 项检查：通过 9，失败 1 ==        (exit 1)
```

删掉临时文件后复跑：**10/10 通过**。

### 验收（2026-09-21 复核后实测）

| 项 | 结果 |
| --- | --- |
| `run_all.py` | **10/10**（探针清单一项同时给出「真跑 offline 3 个」「控制台守卫 32 个」） |
| `pytest` | **95 passed**（新增 `tests/test_system_notice.py` 8 条） |
| `e2e.py`（**不设** `PYTHONUTF8`，中文控制台裸跑） | **95/95（0 skipped）** —— 编码那条修好了，不再需要手动设环境变量 |
| 真机 `vntext_live.py` | 路径修好后可直接跑：DRACU RIOT 7 句台词全干净 + 7 句译文，引擎 `TVP/KIRIKIRI`，`merged=12`，原始行审计漏掉 0 |

### 遗留观察（本轮如实登记，未改代码）

真机自测里出现过「原始行审计报 `漏掉 N 条`」，但**不是清洗规则丢的**：把那些行逐条过规则，
`looks_like_noise=False`、`looks_like_dialogue=True`（例如
`バッカ、お前、自分が学生だなんて語ってどうすんだよ？ 今から“楽園”に行くんだぜ`）。
丢在更前面的**线程门禁**：测试脚本在游戏刚起来、还没选出领跑线程时就连点 6 次，
那几句只从非领跑线程经过，按设计被丢掉（同一次运行 `lines=5 merged=2 gated=1`）。
正常玩法（等画面出来再翻页）不会这样，要复现得「启动瞬间狂点」。
后续方向：冷启动宽限期 —— 前 N 秒不做线程门禁，先把台词收下来再去重。
