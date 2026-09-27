# Aurora 开源化行动清单（按优先级）

> **前提**：本项目为 **单人维护**。因此排序原则不是"功能越多越好"，而是：
> ① 先解锁**别人能用**；② 再解锁**别人能贡献**；③ 然后**降低你自己的维护成本**；④ 最后才是功能对齐。
> 任何会**持续消耗你时间**的东西（社区 SLA、CLA 流程、多平台承诺）优先级一律往后压。
>
> **参照对象**：`gal-launcher`（KamiNeko-pre/gal-launcher，MIT，77 star，6 个 Release，~1843 下载）。
> 它的强项正是 Aurora 现在缺的那一半：**发布流程 + 协作基建 + 产品化首页**。

---

## P0 · 阻塞项（不做的话，"开源"名不副实）

> 这批全部加起来 **1–2 天**，但它们决定了一个陌生人打开仓库后**能不能用、敢不敢用**。

### 1. 加 `LICENSE` ⛔ 最高优先

**现状**：仓库 `license: null`（GitHub 明确识别为无许可证）。无 License = **保留所有权利** —— 法律上没人可以合法使用、修改或分发 Aurora，哪怕你把它公开了。

**建议选 MIT**，理由三条：
- Aurora 的 Python/前端代码**全部自写**，不含第三方源码，许可上没有兼容性约束；
- 你明确参考过的 `gal-launcher` 是 **MIT** —— 用 MIT 可以让"借鉴"这件事在许可层面完全对等，避免"参考了别人却用更严许可"的观感问题；
- Textractor / Locale Emulator / LunaTranslator 是 GPL，但 Aurora 只**通过命令行启动独立进程**、既不分发也不链接它们的代码，这通常不构成衍生作品 —— 但**建议在 README 的"参考的开源项目"一节把这句话写明白**（你现在已经写了大半，补一句许可边界即可）。

**同时要做**：
- `CONTRIBUTING.md` 里加一句 **inbound = outbound**（"提交即同意以 MIT 授权"），不引入 CLA/DCO 这类会拖慢你的流程；
- 仓库里那几张 **Gal Launcher 截图**（`docs/theme-demos/reference/*.jpg`、`docs/images/详情页-Gal Launcher.png`、`docs/images/ux/ref-theme-*.jpg`）加一行来源与用途说明（"设计参考，非代码/素材搬运"），或移出公开仓库 —— 现在它们以"他人 UI 截图"的形式留在你的公开仓库里，配上 MIT 之后容易引起误会。

### 2. `.gitignore` 加 `_compare/`

我这次对比时把解码下来的 gal-launcher 文档放在 `_compare/gal-launcher/`，它现在**未被忽略**（`git check-ignore` 实测 NOT ignored），会被误提交。加一行即可。顺手确认 `data/`、`Aurora.exe`、`_sandbox/`、`_build/` 仍然被忽略（**实测这一块你做得很干净**：`data/` 全目录未跟踪，公开仓库树里没有它，跟踪树里 grep 不到任何 API Key）。

### 3. 发第一个 Release

**现状**：0 个 Release。README 第一句是"双击 `Aurora.exe`"，但 `Aurora.exe` 被 `.gitignore` 排除 —— 也就是说**一个陌生人打开仓库，没有任何东西可以下载**。这是 0 star 最直接的原因，跟代码质量无关。

**两件前置**：
- **给 exe 注入版本信息**：实测 `Aurora.exe` 的 PE 版本资源 **FileVersion / ProductVersion / ProductName / CompanyName 全为空**，用户右键看属性什么都看不到。`tools/build_exe.py` 里加 PyInstaller 的 `--version-file`（或 `resedit`-style 方案）即可。
- **写 Release Notes**：直接照 `gal-launcher` 的做法 —— 每条列"新增 / 改进与修复 / 下载与更新"，并明确写出"未签名 → 可能出现未知发布者提示"（它就是这么写的，很省事且诚实）。

**然后加自动发布**：`.github/workflows/release.yml`，照 `gal-launcher` 的 `release-portable.yml` 模式（`workflow_dispatch` + tag 输入 → **先跑 `run_all.py` + `pytest` 当门禁** → 真打包 → 上传 Release）。你现在 CI 只跑 `build_exe.py --dry-run`，**从不真打包**，这一步顺带把这个缺口补上。

### 4. README 拆成"产品页 + 手册"两层

**现状**：README **594 行 / 67 KB**，开头直接是"快速开始 → 双击 Aurora.exe / 双击 bat"，而"这是什么、为什么值得用、长什么样、现在能做什么/不能做什么"要靠读者自己从 594 行里拼。你有非常漂亮的截图，却埋在第 12 行。

**顶层 60 行只放这五块**（其余整体下沉到 `docs/manual/`，或至少加个 TOC）：
1. 一句话定位 + 一张大厅截图；
2. **下载入口**（指向 Release，而不是"双击根目录的 exe"）；
3. 三到五条卖点（多源匹配免 Key / 转区启动 / **游戏内逐句翻译** / 5 套主题 / 24 MB 单文件免安装）；
4. **边界声明**（下一节单独说）；
5. 指向手册、架构文档、FAQ。

### 5. 一句"边界声明"能省掉未来大量 issue ⭐

这是本次对比最重要的收获之一。请务必在 README 显眼处写明：

> **游戏内翻译目前的形态是「置顶悬浮窗」** —— 译文显示在游戏画面之上的独立小窗里（默认鼠标穿透，`Ctrl+Alt+T` 切换）。
> **把中文直接渲染进游戏自身文本框的"内嵌翻译"（等效原生汉化）尚未实现**；即便最成熟的开源方案 LunaTranslator 也只对部分游戏做到。

理由：`gal-launcher` 的用户 issue #1 第六条要的就是"**内嵌**的翻译功能"。你一旦公开发布，"为什么不是汉化"会成为最高频的提问。**先用一句话挡住，比你以后回答一百次都便宜。**

### 6. 统一对外版本号

**现状：四套版本号并存** —— `aurora/infra/store/paths.py:16` 的 `VERSION = "1.0.0"`、`frontend/package.json` 的 `"version": "2.0.0"`、数据的 `SCHEMA_VERSION = 2`、内部的阶段号 `P8.21`；而且**没有 CHANGELOG**。

**做法**：以 `paths.py` 的 `VERSION` 为**唯一对外版本**；`frontend/package.json` 改为跟随或标记为私有子包；`SCHEMA_VERSION` 只在文档里出现；`P8.x` 退为**内部里程碑**（不进 Release 标题）。再补一个 `CHANGELOG.md` —— 你已经有现成素材：`docs/architecture/13-roadmap.md` 的阶段状态表 + 各阶段交付记录，基本就是一份高质量 changelog，改写即可。

---

## P1 · 社区杠杆（解锁"别人能贡献"）

> 这批的目标只有一个：**让外部贡献进来的东西，恰好是你最缺的**。

### 7. 把「引擎实测规则」做成一等公民贡献通道 ⭐⭐ 最高杠杆

**为什么是它**：`aurora/rules/engines/hooks.json` 的指纹是 `(exe 文件名, 字节数, CRC32)` 三元组，配上 H-code 与清洗档位 —— 这意味着**一条贡献完全不需要写 Python**：用户跑一个游戏、拿到一条 hook 码、填个表单就行。而 galgame 有成千上万部，**这是你一个人永远做不完、而社区能替你做的事**。

**具体做三件**：
1. **`.github/ISSUE_TEMPLATE/engine-rule.yml`**：表单字段直接对应 `hooks.json` 的 schema —— 游戏名 / 引擎 / exe 文件名 / 字节数 / CRC32 / H-code（`H<模式><偏移>@<模块内偏移>:<exe文件名>`）/ 原文样例 / 是否转区 / 是否缺字 / 截图或日志。你 `docs/engines.md:77-95` 里**已经有"测试与反馈模板"**，把那个模板变成 GitHub Issue Form 就行。
2. **给用户一个导出入口**：`tools/export_engine_rules.py` 已经能把规则导出来，把它接成"设置 → 关于 → **导出我的引擎规则包**"，用户点一下就能把 JSON 贴进 issue。
3. **README 里把这个入口放到显眼位置**，措辞就像你现在写的"插件与引擎规则包（社区贡献入口）"那样坦率。

> 参考：`gal-launcher` 的 `.github/ISSUE_TEMPLATE/` 里有一个专门的 `metadata_source.yml`（资料源贡献表单）—— 同一个思路，它已经把"社区贡献一类结构化数据"这件事跑通了。

### 8. Issue / PR 模板（半天工作量，长期省事）

- **`bug_report.yml`**：**必须要求附诊断包**。这是你相对 gal-launcher 的**结构性优势** —— 你已经有 `tools/collect_diagnostics.py`（脱敏设置 + 日志尾巴 + 插件与资料源状态 → zip）。把"请先导出诊断包并附上"写进必填项，能直接省掉一轮轮问答。
- `feature_request.yml`、`.github/ISSUE_TEMPLATE/config.yml`、`.github/PULL_REQUEST_TEMPLATE.md`。
- **技巧（学 gal-launcher）**：把你不想自己做的功能写成 **"【欢迎认领】"** issue —— 它的 #2/#3/#4 就是这个格式：**问题现象 → 期望结果 → 从哪里开始（点名具体文件）→ 验收清单 → 合并后在 README 署名**。对单人项目来说，"把 backlog 变成别人能接的任务"是最高性价比的杠杆。你的 `docs/handover.md` 待办表稍加改写就能发出去。

### 9. `CONTRIBUTING.md` + `SECURITY.md`

**`CONTRIBUTING.md`** 写三条路径 + 三个必须知道的坑：
- 路径：① 提交一条引擎实测规则（不用写代码）；② 写一个资料源/翻译引擎插件（`docs/plugins.md` 已有完整样例）；③ 改核心代码（先读 `docs/architecture/05-layers-and-rules.md`）。
- **坑 1**：`启动 Aurora.bat` / `打包 Aurora.bat` / `调试启动.bat` **必须是 GBK 编码 + CRLF**，用普通编辑器保存会把中文注释和命令行拆坏（改用 `python tools\make_bat.py` 重新生成）；
- **坑 2**：`data/` 是运行时目录且被 gitignore，别往里提交任何东西；改前端后必须 `cd frontend && npm run build`（产物入库 `gl/web/v2/`，有 sha256 指纹守卫）；
- **坑 3**：任何改动都要过 `python tools\checks\run_all.py` + `python -m pytest`，CI 会查。
- 末尾：贡献即同意以 MIT 授权。

**`SECURITY.md`** 重点不是漏洞流程，而是**如实写清插件的信任模型**（你已经写得很好了，直接搬）：
> 插件与 Aurora 同进程、以你的用户权限运行，能读文件、能联网。宿主只保证"插件出错不会带崩 Aurora"，不保证"插件不做坏事"。

### 10. `CODE_OF_CONDUCT.md`

直接用 [Contributor Covenant](https://www.contributor-covenant.org/) v2.1 并注明来源即可（gal-launcher 也是这么做的，1.6 KB）。**如果你不打算真的执行它，就干脆别加** —— 空挂一个行为准则比没有更伤信誉。

---

## P2 · 降低你自己的维护成本

### 11. 先把手上的活收干净

**实测：工作区有未提交的 P8.21 改动**（12 改 / 4 删 / 6 新增，含 `frontend/src/views/CategoriesView.vue`、`core/shell.ts`、`core/store.ts`、`styles/layout.css` 与重建后的 `gl/web/v2` 产物）。

对一个准备开放贡献的仓库来说，**脏工作区是硬障碍**（别人没法干净地 fork/branch）。所以：**先跑一次分类页真机复核 → 提交 → 再开始 P0/P1 的开源化动作。**

### 12. 文档一致性一次性收口（半天）

实测的滞后点，改完就一劳永逸：
- `docs/architecture/README.md`：写"97 个 DOM id / 13 条架构决策记录"，实际是 **99 / 14**；
- `docs/architecture/13-roadmap.md:62`：「明确不做」里仍列着"**前端构建链（Vite/TS）与运行时新依赖**"，但 ADR-0013 已经把它引入了 —— 这条应该删掉或改为"仅此一次例外，已由 ADR-0013 记录"；
- `docs/architecture/p8-frontend-v2.md`：同文件内"主题基线 25 张"与"35 张"、"skin ≤80 行"与"≤200 行"新旧口径并存 —— 你已经在用"保留历史证据"的方式处理，建议统一加一行 `> ⚠️ 历史口径，当前值见 xxx` 的标注，读者就不会误解。

### 13. 删掉一次性脚本

`frontend/scripts/_migrate_layout_css.py` 脚本头自己写着"跑完即删"，但文件还在，而且**内部硬编码了绝对路径** `C:\Users\HuHu1\Desktop\Tasks\v4.1\Aurora\...`。删掉它（迁移产物已在 `layout.css` 里入库）。

### 14. 关于代码签名

`gal-launcher` 的处理方式是**不签名 + README 明确告知**（"如果 Windows 提示未知发布者，这是因为当前版本没有代码签名证书，确认文件来自本仓库 Release 后继续运行即可"）。**建议照抄这个做法**：真签名要买证书，而这句话几乎零成本地解决了同一问题。

---

## P3 · 功能对齐（对照 gal-launcher 的差距）

> 这一档**不是现在做**，而是排进 backlog，其中大部分可以做成"欢迎认领"issue。

| 能力 | gal-launcher | Aurora | 建议 |
|---|---|---|---|
| **存档管理** | 已实现 IPC（`game:saveBackups` / `createSaveBackup` / `restoreSaveBackup`） | `docs/handover.md:173` 中优先级待做 | **这一档里性价比最高**：你已有 `aurora/platform/proctree.py` + 路径推断能力，做"存档目录快捷方式 + 手动备份/恢复"是顺水推舟 |
| 书架 / 跨分类总览 | 有（各主题自带收藏页） | ⏳ 分类页已承担整理，跨分类总览未做 | 中优先级，能复用现有海报墙组件 |
| 手柄导航 | ✅ 0.4.0 已做 | ⏳ 明确排后 | 适合做"欢迎认领"issue |
| 沉浸式全屏 | ➖ 0.4.0 已做，issue #4 仍在征集"真正全屏 + 窗口状态恢复" | ❌ | 适合做"欢迎认领"issue |
| 批量导入 | ✅ 0.4.0："选总目录 → 收录第一层游戏文件夹 → 优先唯一含 `chs` 的 EXE" | ➖ 有下载目录监听 + 拖文件夹（向下 3 层） | 它的"优先含 chs 的 EXE"启发式值得抄进你的拖放/扫描逻辑 |
| 游戏超分（Magpie） | ✅ 四档 + 自动部署 | ❌ 明确排后 | 低优先级；注意它为此写了一个 9.7 KB 的 `invoke-magpie.ps1` |
| 主题数量 | 6 套（每套改布局） | 5 套（同一套布局换皮） | 见 P4-16 |

---

## P4 · 需要先做"决策"而不是"任务"的两件事

### 16.（决策）主题范式：**建议明确不走"一主题一布局"**，并写成 ADR

你自己已经点出了关键矛盾：Gal Launcher 每主题一个独立布局（6 个 Layout 组件 + 5 份 22–46 KB 的主题 CSS），而 Aurora 的大厅有**三种布局**（环形队列 / 平铺横滑 / 大图侧列表），跟着它走等于推倒重来。**我建议不走那条路**，理由：

1. **单人维护扛不住**：6 份布局意味着每个布局改动都要在 6 处验证；gal-launcher 那 6 份布局已经出现"某个主题的封面尺寸异常/滚动条缺失"这类只在单主题复现的 bug（它的 issue #2、#3 就是这么来的），而它至少还有社区。
2. **Aurora 的身份在几何，不在皮肤**：环形队列的 `rotateY` + 透视 + 首尾相接是你的原创识别度，`layout.css` 2137 行只有一份，`e2e`/`visual` 的判据全压在它上面（"环形几何是 e2e/visual 的判据"）——**多布局会让这套量化验收塌掉**。
3. **你已经在做正确的事**：现在是"5 皮肤 × 3 布局"的正交结构，而且有令牌契约、皮肤行数上限、选择器作用域、圆角单调性、`--fx-blur` 只允许 aurora 非零…… 这些守卫是**为"皮肤可扩展"量身定做的**。

**建议动作**：写一份 **ADR-0015「主题＝皮肤，布局保持正交；不采用一主题一布局」**，把上面三条固化下来。好处有二：① 消除"要不要跟 gal-launcher"的反复摇摆；② 明确告诉贡献者"加主题的正确姿势是加 3 个 CSS 文件"，这本身就降低了贡献门槛。

> 如果将来真想让主题改布局：正确方向是**把"布局"提升为与"皮肤"并列的第二个维度**（`data-layout` × `data-style`），而不是把两者焊死。但这件事的收益远小于成本，建议明确不做。

### 17.（决策）"内嵌翻译"立项与否，在路线图里写清楚

现在 `README.md:323` 描述的"缺字内存补全"用到 `OpenProcess + ReadProcessMemory`（**只读**），这是很克制的技术路线。而真正的"内嵌翻译"需要**把译文写回游戏渲染流程**（改写内存 / 注入 / HOOK 绘制），风险与工程量都是另一个量级 —— 你自己也判断"又是大工程"，而且 LunaTranslator 也只覆盖部分游戏。

**建议**：在路线图里把它写成一条**显式条目**，二选一：
- **暂不做**：写清"当前提供悬浮窗；内嵌翻译（渲染进游戏文本框）不在近期范围，理由：需注入/改写游戏渲染，风险与兼容成本远超收益，且已有 LunaTranslator 覆盖部分场景"。—— 这条声明配合 P0-5 的边界声明，能彻底关掉这个问题。
- **探索性立项**：写成 spike（先做 1 个引擎的可行性验证，明确"不承诺通用"）。

**无论选哪个，都别留白** —— 留白会持续产生"为什么不是汉化"的 issue。

---

## 附一 · 一周最小闭环（建议按这个顺序做）

| 天 | 动作 | 产出 |
|---|---|---|
| D1 | 提交 P8.21 收口 + 分类页真机复核；`.gitignore` 加 `_compare/` | 干净的工作区 |
| D1 | 加 `LICENSE`（MIT）+ README 里补许可边界说明 | 法律上"可开源"了 |
| D2 | README 顶层重写（产品页 + **边界声明**）；`docs/manual/` 下沉 | 陌生人 30 秒内看懂并能下载 |
| D3 | `tools/build_exe.py` 注入 PE 版本信息；统一版本号；补 `CHANGELOG.md` | 产物可识别 |
| D4 | `.github/workflows/release.yml`（门禁 + 真打包 + 上传）；打 `v1.0.0` 发**首个 Release** | **从 0 到 1：别人终于能用** |
| D5 | `engine-rule.yml` + `bug_report.yml` + `feature_request.yml` + PR 模板 | **从 1 到 N：别人终于能贡献** |
| D6 | `CONTRIBUTING.md` + `SECURITY.md`；把手柄/全屏/存档写成 3 个"欢迎认领"issue | 贡献路径闭合 |
| D7 | ADR-0015（主题范式）+ 路线图里写清"内嵌翻译"条目 + 文档一致性收口 | 决策冻结，不再摇摆 |

> 这一周做完，Aurora 就是一个**结构健全的开源项目**了 —— 而且投入的主要是"表达"和"流程"，不是新功能。

## 附二 · 一句话总结优先级

**先让陌生人能用（License + Release + 首页），再让陌生人能贡献（引擎规则表单 + 模板），
然后把自己的维护成本降下来（收干净工作区 + 文档一致性 + 自动发布），最后才谈功能对齐。**

至于 gal-launcher 的那些主题、手柄、超分 —— 它们是"让人想装"，而 Aurora 现在缺的是"让人装得上"。
**你已经有 24 MB 单文件、零第三方运行时依赖、14 项离线守卫、真实机验证的翻译链路 —— 这些都比多两套主题值钱，只是它们现在还没被人看见。**
