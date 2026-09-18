# 视觉小说引擎清单（钩子适配进度表）

这份清单用来推进「逐引擎攻」：Aurora 的游戏内翻译优先用 Textractor 钩子拿原文，
钩子不行的引擎再走 OCR。下面的「钩子」指的是 Textractor 自带的**引擎级**钩子
（来源：Textractor 源码 `texthook/engine/engine.h`，截至 2026-09 共 115 个）；
不在这张表里的引擎只会退化成通用 GDI 钩子，通常就是少女之剑那种「缺字」下场。

> 说明：我们**不复制** Textractor / LunaHook 的引擎表与钩子码数据，只记录自己实测
> 出来的结论；下面每一行「已测」都是真机跑出来的。

## 一、已通过测试

| 引擎 | 测试作品 | 结论 | 备注 |
| --- | --- | --- | --- |
| **TVP/KIRIKIRI**（32 位） | DRACU RIOT!、RIDDLE JOKER | ✅ 可用（已固化规则） | 一句台词会以「逐字×3 / ×2 / 干净版」三种形态到达，还会带重复的人名前缀；Aurora 自动还原成一句。RIDDLE JOKER 有两条约同名钩子线程交替抢先，已按「先门禁、再去重」处理 |
| **Escu:de** | 悠刻のファムファタル | ✅ 可用 | 长句会**折行**分多条打印（只有第一条带 `[handle:…]` 头），说话人名字单独一条 —— 都已自动并回/并进下一句 |
| **Leaf（Aquaplus）** | WHITE ALBUM2 | ✅ 可用 | 同进程内有乱码线程、菜单栏线程、视频窗口标题（`ActiveMovie Window`）、视频文件名（`mv01`）需要过滤；短台词「あ…」也要算台词 |
| **CatSystem2 / cs2（Ares）** | 灰色的果实 | ✅ 可用 | 用户私测通过 |
| **CMVS** | 天津罪 | 待补实测记录 | 库里已有该作品，随时可回归 |
| **SiglusEngine / Siglus（VisualArts·KEY）** | Summer Pockets REFLECTION BLUE | ✅ 可用（规则已固化） | 一个进程里会有 12+ 条钩子线程：系统线程**疯狂刷屏**（场景名 `10_プロローグ0725` 重复 257 次、`__sys_scdata_init__`、资源表 `l_rb__sys_…`、`nonenonenone…`），另有若干条只吐汉字、缺假名的「缺字变体」。Aurora 现在：把系统刷屏按**原始文本**判掉（重复 token / 超长无句读 / 片段反复出现 → 整个线程标记为刷屏，后续全丢）、领跑线程改按「带句读的句子数」选（所以自动锁到真文本线程）、同一句的缺字变体（干净句的**子序列**）直接并掉。实测 8 句连续翻页全对、原始行审计漏掉 0 |
| **BGI / Ethornell（オーガスト、Sprite 等）** | 穢翼のユースティア | ✅ 可用（规则已固化） | 同一个进程里有两条钩子线程一起吐同一句：引擎级 `BGI` 钩子给完整正文（`視界を黒い何かが塞いだ。`），`TextOutA`/`ExtTextOutW` 这两条按字形抓的 GDI 钩子给缺字版（`視界黒塞`）和乱码版。Aurora 现在先把候选行压住 `variant_settle`（BGI 档为 0.6s），等同一批的两个版本都到齐，只翻完整那份（缺字版按「完整句的子序列」并掉，实测 4/4 并掉、原始行审计漏掉 0）。`vnreng` 日志里能看到 `BGI2: pattern found but the function offset is invalid` —— 说明 Textractor 的 BGI2 专用钩子对不上这个版本，真正干活的是随后注入的通用 `BGI` 钩子，**不用手动选钩子** |
| **WillPlus / AdvHD** | 少女之剑与秘密的协奏曲 | ✅ 可用（两级：**实测 hook 码** + **内存补全**） | Textractor 自带的 WillPlus 系钩子对不上这类 exe：`WillPlus` 报 `function call not found`、`WillPlusW/A` 找不到特征码、`WillPlus2` 把地址算到了 Intel 显卡驱动 `igc32.dll` 上（回显 `HQ-8*0@E8EB90:igc32.dll`，吐乱码）；只剩按字形抓的 `GetGlyphOutlineW`，而引擎字形有缓存 → 一行只抓到零星几个字（实测「出会って…打ち明けた」只抓到「出会　打明」）。两条出路：<br>① **专用 hook 码**（我们实测过、最稳）：文本函数在 `AdvHD_crack.exe` 的 `0xA22E`（基址 0x400000，未开 ASLR），用 UTF-16 读参数 → `HQ-4@A22E:AdvHD_crack.exe`（`Q`=UTF-16、`S`=字节串、`V`=UTF-8，语法见 Textractor `host/hookcode.cpp`）。Aurora 按「文件名+字节数+CRC32」自动带出这条码；<br>② **内存补全**（换游戏也不用再找地址）：缺字版的字都在真句里按顺序出现，而真句就在进程内存里 —— 只读扫一遍内存、按子序列/公共子序列/汉字档匹配取最紧凑那句，**不需要任何地址、不注入、不会崩游戏**。实测把 `つの物思耽で 内で我返`、`郷愁抱意けど そ出`、`空木うつぎ日向ひなた１年間留学え本へ飛行中`（注音混入）都还原成了完整句；4 字级的极短残片偶尔配不出来，这时保留原样。<br>**注意**：`attach` 之后不能立刻发钩子码（会把 CLI 顶掉、一行文本都收不到），要等 CLI 打印「管道已连接」再发 —— Aurora 已处理 |

## 二、待测：Textractor 有专用钩子，按优先级排

| 优先级 | 引擎（钩子名） | 代表作品 | 为什么值得测 |
| --- | --- | --- | --- |
| ~~★★★~~ | ~~**SiglusEngine**~~ | ~~Summer Pockets、Angel Beats! -1st beat-~~ | 已用 Summer Pockets REFLECTION BLUE 实测通过（见上表），换成其它 Siglus 作品可以再验一次规则通用性 |
| ~~★★★~~ | ~~**Ethornell / BGI**~~ | ~~穢翼のユースティア（オーガスト）、蒼の彼方のフォーリズム（Sprite）~~ | 已用 穢翼のユースティア 实测通过（见上表）；同引擎的 蒼の彼方のフォーリズム / 大図書館の羊飼い 可以再验一次规则通用性 |
| ★★★ | **CatSystem2** | グリザイア三部曲（フロントウイング）、ういんどみる、クロシェット | 已用「灰色的果实」私测通过，可再补一部确认规则通用 |
| ★★☆ | **RUGP** | マブラヴ、君が望む永遠（âge） | 老牌大厂自研引擎，钩子单独存在 |
| ★★☆ | **NeXAS** | Dies irae、相州戦神館學園（light） | 文字量大、特殊字形多 |
| ★★☆ | **Nitroplus** | 沙耶の唄、君と彼女と彼女の恋。 | 演出花，文本流形态多 |
| ★★☆ | **Alice / System43** | ランス10、イブニクル（アリスソフト） | System4 系两套钩子，界面文本混杂 |
| ★★☆ | **Eushully** | 戦女神、天結いキャッスルマイスター | 自研引擎，SLG 界面 + 台词混合 |
| ★★☆ | **NScripter / PONScripter** | ひぐらしのなく頃に、うみねこのなく頃に | 老引擎，汉化版仍在流通 |
| ★★☆ | **Nekopack** | NEKOPARA | 现代作品，Steam 上就能买 |
| ★☆☆ | **RealLive** | AIR、CLANNAD（初版） | Siglus 的前代引擎（维基记载两者的替代关系） |
| ★☆☆ | **YU-RIS** | 中小厂/同人（维基举了アオリオ等） | 覆盖面广但资料少 |
| ★☆☆ | **Malie / Majiro / QLIE / Pal / Silky's / Debonosu / TinkerBell / Waffle / Candy / CaramelBox / AmuseCraft** | 各自中小厂作品 | 逐个攻，补齐清洗规则库 |
| ★☆☆ | **Wolf（Wolf RPG Editor）** | 魔女の家、青鬼 等独立游戏 | RPG 系文本多、格式杂 |
| ★☆☆ | **Ren'Py** | Doki Doki Literature Club 等海外/同人 | 海外作品常见 |
| ★☆☆ | **5pb** | STEINS;GATE | 科学 ADV 系列 |
| ★☆☆ | **AdobeAir / AdobeFlash10** | 同人 Flash/AIR 游戏 | 老同人作品 |

## 三、没有专用钩子（OCR 靶子，最值得测）

| 类型 | 代表作品 | 说明 |
| --- | --- | --- |
| **Aquaplus 自研** | うたわれるもの、ダンジョントラベラーズ | 不在 115 个钩子里，大概率只能 OCR |
| **Unity / Unreal / Godot / GameMaker** | 近两年新作越来越多（同人与商业都有） | 引擎多样化，Textractor 无对应钩子 |
| **小厂自研 DirectX 引擎** | 与少女之剑同类 | 先试钩子，缺字就转 OCR |

> 掌机模拟器钩子（`OtomatePSP`、`5pbPSP`、`TypeMoonPS2`…共 24 个）是给 PPSSPP/PCSX2
> 用的，对原生 PC exe 无效，可以忽略。

## 四、测试与反馈模板

1. 用最新 `Aurora.exe`；设置 → 游戏内翻译里把引擎切到「自动」，或按上面表格直接指定钩子。
2. 打开游戏 → 游戏页「翻译」→ 连翻 20 句，观察：
   - 有没有文本；
   - 有没有**缺字 / 重复 / 一句话被拆成几条**；
   - 面板里「当前线程」是不是**真台词线程**；
   - 译文是否跟当前文本对得上。
3. 反馈给我四样即可：**游戏名、面板显示的引擎名、线程列表（名字 + 样例）、出问题句子的前后原文**。

手边工具：

| 脚本 | 用途 |
| --- | --- |
| `python tools\vntext_live.py --game <关键字>` | 真机自检：自己启动游戏 → 挂钩子 → 自动翻页 → 断言台词干净且有译文，并做「原始行审计」（认出 / 只有人名 / 噪声 / 半截碎片 / 漏掉） |
| `python tools\vntext_rawdump.py --pid <pid>` | 把 TextractorCLI 的原始输出逐行摊开，定位「哪条线程才是完整文本」 |
| `python tools\vntext_hookprobe.py --pid <pid>` | 逐个试钩子名，看引擎专用钩子在目标游戏上能不能出干净文本 |
| `python tools\vntext_probe.py` | 离线回归：假 CLI + 真样本（含各引擎实测行）跑一遍清洗与翻译链路 |

## 五、参考

- Textractor 源码（引擎钩子清单、注入日志格式）：<https://github.com/Artikash/Textractor>
- 项目 README 的「游戏内翻译」小节：排错步骤与本机依赖（TextractorCLI、日语 OCR 组件、转区）
