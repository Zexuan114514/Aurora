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
