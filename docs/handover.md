# Aurora 交接文档

> 写给下一个接手的人（也可能是几个月后的自己）。**先读这份，再读
> [`architecture/README.md`](architecture/README.md)（为什么这么设计）与
> [`../README.md`](../README.md)（有什么功能）。**
> 最后更新：2026-09-26（前端 v2 已扩展为五主题；P8.19 按钮皮肤与图标打包链已接入，P8.20 提示 / 悬浮窗 / 输入框可读性修复、
> P8.21 找钩子事实口径、线程诊断与小窗口滚动已完成，
> 主题按钮和打包图标已由使用者实测；P8.11–P8.18 的真机 bug 与修复详见
> [`handover-p8-frontend-v2.md`](handover-p8-frontend-v2.md)）
>
> 前端 v2 与主题外观重构（P8.4）另有一份专项交接：
> [`handover-p8-frontend-v2.md`](handover-p8-frontend-v2.md)。

## 1. 这是什么 / 当前状态

Aurora 是一个 **Windows 单机 galgame 启动器**：管游戏库、抓元数据、记账游玩时长、
转区启动（Locale Emulator），并在游戏里做**实时取词 + LLM 翻译**（钩子优先、OCR 兜底）。

| 项 | 现状 |
| --- | --- |
| 版本 | `1.0.0`（`aurora/infra/store/paths.py::VERSION`） |
| 运行形态 | 源码 `python main.py`；发布 `Aurora.exe`（PyInstaller 单文件，约 24.5 MB） |
| 开发环境 | Windows + Python 3.13（本机是 Anaconda）；`webview`(pywebview) + `winrt-*` 是仅有的运行时依赖 |
| 用户数据 | 与本机绑定，**不进仓库**：`data/`（库、设置、素材、缓存、日志） |
| 测试现状 | `pytest` 全绿、`tools/checks/run_all.py` **14/14**、`tools/e2e.py` **101/101**、`tools/contrast.py` **40/40**、`tools/visual.py` 主题矩阵 **35/35（偏差 0）** |
| 主题 / 图标 | 五套主题（极光 / 画廊 / 放映厅 / 收藏架 / Atelier）× 深浅；512×512 RGBA 源图生成含 7 尺寸的 `aurora.ico`，打包脚本自动重建并刷新 Explorer 缓存 |
| 真机矩阵 | DRACU RIOT（KiriKiriZ）/ 少女之剑（WillPlus+专用码）/ アマカノ３（Artemis）/ 白色相簿2（Leaf）… 见 [`engines.md`](engines.md) |
| 远端 | `origin = https://Zexuan114514@github.com/Zexuan114514/Aurora.git`（URL 里带用户名，否则 GCM 会卡住） |

## 2. 五分钟上手

```powershell
# 跑起来（源码）
python main.py                      # 或双击「调试启动.bat」（带控制台、会打印日志）

# 自检（按顺序，全绿再动手改）
python tools\checks\run_all.py      # 14 项离线检查：契约 / 分层 / 引擎规则 / 启动冒烟 / 设置键名等
python -m pytest                    # 单元 + domain 金样本 + 迁移 + 插件 + 诊断包
python tools\e2e.py                 # 真窗口端到端 101 项（会自己起应用，跑完自动关）
python tools\visual.py              # 封面/缩略图真的画出来了没有
python tools\contrast.py            # 真机对比度：5 套风格 × 深/浅 × 2 页（40 点；正文 ≥4.5 / 大字号 ≥3.0）

# 打包（打包前必须确认没有 Aurora.exe 在跑，否则 WinError 32）
python tools\build_exe.py           # 产物：根目录 Aurora.exe
```

代码变了以后，**别跳过 `run_all`**：它会在你忘记同步契约、把探针写死旧路径、
或让某一层越权 import 时直接变红（见 `tools/checks/*`）。

## 3. 代码地图

分层见 [`architecture/05-layers-and-rules.md`](architecture/05-layers-and-rules.md)：
`ui → app → domain`，`infra` 实现端口，`platform` 只放 Win32 原语，**组合根只有
`gl/api.py` 的 `Api()`**。

| 位置 | 内容 |
| --- | --- |
| `main.py` | 进程入口：单实例、数据目录、迁移、能力探测、窗口、托盘、拖放 |
| `gl/api.py` | 组合根（196 行）：装配 store / 适配器 / 服务 / 桥接 mixin |
| `aurora/domain/` | 纯逻辑：文本清洗规则、匹配打分、引擎规格与 H-code、会话结算 |
| `aurora/app/services/` | 用例服务：library / metadata / launch / vntext / hooksearch / translation / settings / plugins / diagnostics |
| `aurora/infra/` | IO：store(v2)、资料源、Textractor 子进程、OCR、翻译、下载监听、本地资源服务 |
| `aurora/platform/` | ctypes 原语：winapi / tray / hotkey / screencap / memmatch / hookfinder / proctree |
| `aurora/ui/bridge/` | 7 个桥接 mixin（**方法名即契约**，见 `contracts/bridge-contract.json`） |
| `frontend/src/**` | 前端源码（Vue 3 + TS：`core/` / `views/` / `panels/` / `features/`），构建产物在 `gl/web/v2/`（P8.9 删 v1，见 ADR-0014） |
| `tools/` | 33 个自检/打包脚本（清单：`tools/checks/tools-manifest.json`） |
| `data/`（不进库） | `state/`（库/设置/会话）、`covers|backgrounds|icons|vntext|downloads|cache|logs` |

## 4. 游戏内翻译子系统（最复杂、最常出问题的地方）

### 4.1 链路

```
TextractorCLI（用户自装，x86/x64 各一份）
   └─ 钩子文本 → VnTextEngine（aurora/infra/vntext.py）
         ├─ 清洗/折行并回/说话人合并/去重  → 一条条「台词」
         ├─ 缺字补全 memmatch（只读扫内存，见 4.3）
         └─ OCR 兜底（Windows.Media.Ocr，需要日语组件）
   └─ 台词 → LineTranslator（aurora/infra/linetrans.py）→ 流式 LLM / 免费接口 / 插件
         └─ 悬浮窗（aurora/ui/overlay.py + frontend/src/overlay/）与翻译面板
```

### 4.2 引擎覆盖（现状）

完整矩阵与实测样本见 [`engines.md`](engines.md)。要点：

* **Textractor 自带引擎钩子**可用：TVP/KIRIKIRI、Leaf、BGI/Ethornell、Escu:de、Siglus、CatSystem2/Ares…
* **必须自己找地址**：WillPlus/AdvHD（自带 WillPlus 系钩子全失配）、Artemis/Emote（D3D11 自绘字）。
  两者都已在「设置 → 游戏内翻译 → 找不到文本？开始侦测」里有**自研钩子查找器**
  （`aurora/platform/hookfinder.py` + `app/services/hooksearch.py`，签名播种 + 寄存器偏移 + 磁盘镜像扫描）。
* 实测有效的码按「文件名 + 字节数 + CRC32」写进规则包（内置 `aurora/rules/engines/*.json`，
  用户覆盖 `data/rules/engines/*.json`），命中即自动带上。

### 4.3 必须记住的不变量（都是真机事故换来的）

1. **缺字补全不是万能的，跑错地方会拖死全局**：`MEMORY_COMPLETION_SKIP_ENGINES`
   （TVP/KIRIKIRI、Leaf、BGI、Escu:de、Siglus、CatSystem2/Ares）**不做**补全 ——
   这些游戏正文本来就完整，补全只会白扫 70 秒并补出坏句。WillPlus/Artemis 才做。
2. **内存扫描永远不许占热路径**：`memmatch.complete_async/snap_async` 最多等 2.5 秒，
   超时交给后台；`_SCAN_SLOT` 保证同一时间只有一个扫描。见
   [`perf-diagnosis-2026-09-21.md`](perf-diagnosis-2026-09-21.md)。
3. **推送与悬浮窗都不许阻塞**：引擎状态推送去抖 250 ms（`_push_status(force=…)`），
   悬浮窗更新是「只留最新一份 + 后台单线程 + 连续失败 3 次自动停用」。
   回归网：`tests/test_status_debounce.py`、`tests/test_overlay_update.py`。
4. **补完版不许只进缓存**：`complete_async/snap_async` 超时放行时先在引擎里**登记认领**
   （`_arm_completion`：只有认领之后发射的缺字版才有资格），后台扫出结果后作为
   **同一句的新版本**补发（发射带 `revise_of` = 缺字版的发射序号，认领窗口 150 秒）。
   翻译侧按序号**原位替换**历史（`LineTranslator._finish`），缺字版的译文后到就直接丢；
   要补发的那句已经是旧台词时带 `silent` —— 只修面板，不把悬浮窗顶回旧句子。
   回归网：`tests/test_memory_completion_reemit.py`、`tests/test_linetrans_revision.py`。
5. **冷启动 30 秒不做线程门禁**：游戏刚起来、领跑线程还没选出来时连点翻页，前几句
   常先从别的线程到，会被门禁当「弱行」整句丢掉（真机自测「审计漏掉 N 条」的真凶）。
   `COLD_START_GRACE = 30.0` 内只挡**不像台词**的行；去重/并合照常，所以同一句从两条
   线程来仍只翻一次。回归网：`tests/test_cold_start_grace.py`。

### 4.4 排错关键字（`data/logs/aurora.log`）

| 想查什么 | 看这一行 |
| --- | --- |
| 钩子启没起来、为什么走了 OCR | `vntext start: mode=… cli=…(位) wanted=[…] mismatch=…` / `vntext start result:` / `vntext hook unavailable → OCR: <原因>` |
| 取了什么文本、什么时候发射的 | `vntext in [线程] '原文' -> '清洗后'`、`vntext emit [hook\|ocr] '…'` |
| 一句为什么被丢 | `vntext gated` / `same text merged`（10 秒窗内）/ `dup merged` / `short fragment merged` / `variant merged` |
| 缺字补全有没有乱跑 | `memmatch:` / `vntext memory completed:`（**引擎级钩子的游戏这里应该是 0 行**） |
| 补完版有没有补发回来 | `vntext completion arrived:`（后台扫到结果）→ `vntext revision of #N:`（认领到那条缺字版）→ `vntext revision [#N] ->`（补发出去）；认领不到会看到 `vntext revision dropped (过期)` |
| 翻译慢在哪一段 | `linetrans done [llm\|free\|cache] '…' (N.Ns)`（N 是排队 + 请求总耗时） |
| 冷启动有没有被门禁吞句子 | `vntext gate held (cold start)`（30 秒宽限期内放行的非领跑线程台词）/ `linetrans dropped (已被补完版替换)`（缺字版译文来晚了，被补完版顶掉） |
| 悬浮窗 | `overlay update failed` / `overlay 连续更新失败，已停用悬浮窗` |
| 一键打包全部状态 | 设置 → 关于 → **导出诊断包**（或 `python tools\collect_diagnostics.py`） |

## 5. 数据与配置

* **v2 布局**（P2 迁移）：`data/state/library.json`（games + bookshelves）、
  `data/state/settings.json`、`data/state/sessions.jsonl`；v1 的 `data/library.json`
  只在迁移时读一次。**探针脚本一律用 `tools/_common.layout()` 取路径，别再手拼字符串**
  （写死 v1 路径会被 `run_all` 的路径守卫拦下）。
* 每游戏关键字段：`vntext_hook`（专用 hook 码）、`vntext_ocr_region`、`locale_enabled/locale_guid`、
  `status`、`bookshelf_ids`、`play_count`、`sessions`。
* 翻译设置：`translate_provider`（`auto` / `free` / `plugin:<id>`）、`translate_api_key`、
  `translate_model`、`vntext_engine`（`auto|hook|ocr`）、`vntext_tractor_path`、
  `vntext_auto_start`、`vntext_context_lines`、`vntext_overlay{…}`。
* **`data/` 永远不进仓库**（含 API Key）；诊断包已做脱敏（`***`）。

## 6. 治理：什么在替你看着

| 守卫 | 管什么 |
| --- | --- |
| `run_all.py` 14 项 | 契约快照（109 方法 / 14 事件 / 103 前端调用点）、依赖白名单、去敏夹具、探针清单（含**真跑 offline 脚本**与控制台/路径守卫）、架构基线、桥接转发目标、引擎规则包、分层规则、打包清单（含**悬浮窗入口存在**）、前端构建指纹、主题契约（含令牌值域）、设置键名、启动冒烟 |
| `pytest` | domain 金样本、数据迁移/去抖/回滚、插件、诊断包，以及取词链路的回归网（推送去抖 / 悬浮窗非阻塞 / 缺字补全门禁与补发 / 冷启动宽限期 / 文学重复 / 窗口止损） |
| `e2e.py` 101 项 | 真窗口：大厅/游戏页/设置/分类/拖拽/缩放/翻译面板/悬浮窗/hook 码存取/主页启动与右键菜单 |
| CI（`.github/workflows/offline-checks.yml`） | run_all + `build_exe --dry-run` + pytest + 迁移专项 + 诊断包 |

改桥接方法名 = 改契约：必须同步 `docs/architecture/contracts/bridge-contract.json`
（`python tools/checks/update_contract.py --write`）并在提交信息里说明。

## 7. 硬约束（踩过的坑，别重犯）

1. 两个 `.bat` 必须 **GBK + CRLF**，只能由 `python tools\make_bat.py` 生成。
2. 中文控制台里 `print` 带「⋯」会抛 `UnicodeEncodeError`：探针脚本统一
   `tools/_common.setup_console()`（**只放宽 errors，不把 cp936 强改 UTF-8**）。
3. `tools/*-report.txt` 是**运行时产物，不再跟踪**（`.gitignore` 已忽略）；`_sandbox/` 同样。
4. 桥接层不许直接 import `infra`，`domain` 不许碰 IO —— `check_layers` 会红。
5. 事件只能经 `aurora/ui/bridge` 的统一出口推给前端（不要自己 `evaluate_js`）。
6. 外部工具（Textractor / LE / 7-Zip / LunaTranslator）**只对接、不打包、不改动**；
   引擎表与 hook 码只写我们自己实测出来的。

## 8. 待办与下一步

| 优先级 | 事项 | 备注 |
| --- | --- | --- |
| 高 | **真机复验两条新链路** | ① 少女之剑（WillPlus，必须靠内存补全）：连翻 20 句，日志要能看到 `vntext completion arrived:` → `vntext revision of #N:`，面板里那句从缺字版换成完整句；② 任意游戏：启动瞬间连点 6 次翻页，审计应该「漏掉 0」（日志里是 `vntext gate held (cold start)`）。两条都只有离线回归网，没上过真机 |
| 中 | RIDDLE JOKER 复测 | 双同名线程交替抢先已修（P3 记录），冷启动宽限期改动后建议照 `engines.md` 模板再跑一次 20 句 |
| 中 | 书架页 | 分类页已承担整理，跨分类总览还没做 |
| 中 | 存档管理 | 待做「存档目录快捷方式 + 手动备份/恢复」 |
| 低 | 手柄 / 多主题 / Magpie / CI 自动发布 | 明确排在后面 |
| 中 | [前端体验反馈](frontend-ux-feedback.md)第 4 项：收藏架要不要走 Atelier 语言 | 已由 P8.17–P8.19 决策并落地为正式第五套主题；`docs/theme-demos/atelier/` 保留为设计来源，当前区分度 23.9 |

## 9. 参考的开源项目与许可

只用思路、只调公开接口，**不复制 GPL 代码、不打包第三方二进制**：
Textractor（钩子主路径）、Locale Emulator（转区）、LunaTranslator（钩子覆盖率参考，
README 里给用户指路）、MisakaHookFinder（「找特殊码」思路）、FuckGalEngine / SExtractor
（WillPlus / Artemis 文本提取思路）、pywebview、PyInstaller、Windows.Media.Ocr。
详细清单见 `README.md` 末尾。
