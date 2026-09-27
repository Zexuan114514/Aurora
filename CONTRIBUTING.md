# 参与贡献

Aurora 是单人维护的 Windows 本地游戏启动器。最受欢迎的贡献不是大重构，而是**能被复现的小块事实**：
一条实测 hook 码、一个资料源、一段能解释清楚的修复。

贡献即表示你同意：该贡献按本仓库的 [MIT License](LICENSE) 对外发布（inbound = outbound，不需要 CLA / DCO）。
第三方软件、商标、截图和图片不因这份许可获得再许可，提交素材时请说明来源与授权范围
（见 [第三方参考素材说明](docs/THIRD-PARTY-ASSETS.md)）。

## 三条路径

### 1. 交一条引擎实测规则（不用写代码）

**这是杠杆最高的一条路**：galgame 有成千上万部，引擎适配靠一个人做不完。
规则包按 `(exe 文件名, 字节数, CRC32)` 三元组匹配，配上 H-code 与清洗档位 —— 你不需要读核心代码。

做法：

1. 在游戏里让翻译能出文本（设置 → 游戏内翻译；抓不到就点「找不到文本？开始侦测」）；
2. 设置 → 关于 → **导出我的引擎规则**：生成一份规则包 JSON + 一份照着表单排好的说明；
3. 开一个[「引擎实测规则」issue](https://github.com/Zexuan114514/Aurora/issues/new?template=engine-rule.yml)，粘贴提交。

不想开 issue 也行：把整理好的 JSON 丢进 `data/rules/engines/`（用户规则包，同指纹时覆盖内置），
能用了再把内容贴到 issue 里，让下一个人不用重复折腾。格式与校验规则见 [docs/engines.md](docs/engines.md)。

### 2. 写资料源 / 翻译引擎插件（只写 JSON 或一个 Python 文件）

插件放进 `data/plugins/`，不用改主仓库。接口、样例与加载顺序见 [docs/plugins.md](docs/plugins.md)；
**动手前请先读 [SECURITY.md](SECURITY.md)** —— 插件与 Aurora 同进程、同权限运行。

### 3. 改核心代码

先开 issue 说清楚要解决什么，再动手。动手前读：

- [分层与规则](docs/architecture/05-layers-and-rules.md)：`domain` 保持纯计算，`ui` / `app` 不直接碰 `infra`；
- [架构总览](docs/architecture/README.md) 与相关 ADR；
- [契约文档](docs/architecture/contracts/)（动了桥接 / 数据 / 事件时）。

## 三个必须先知道的坑

1. **bat 脚本必须是 GBK + CRLF**：`启动 Aurora.bat`、`打包 Aurora.bat`、`调试启动.bat` 用普通编辑器保存
   会把中文注释和命令行拆坏。要改就用 `python tools\make_bat.py` 重新生成。
2. **`data/` 是运行时目录**：游戏库、日志、插件、用户规则都在里面，且已被 gitignore —— 别往仓库里提交任何东西。
   改前端源码后必须 `cd frontend && npm run build`，把产物一并提交（`gl/web/v2/`，有 sha256 指纹守卫）。
3. **任何改动都要过门禁**：`python tools\checks\run_all.py` + `python -m pytest`，CI 会查；
   动了打包相关的东西再跑一次 `python tools\build_exe.py --dry-run`。

## 提交 PR

1. Fork → 从 `main` 开一个分支（建议 `fix/…`、`feat/…`）；
2. 按上面的门禁自检，顺手更新受影响的文档；
3. 按 [PR 模板](.github/PULL_REQUEST_TEMPLATE.md) 填：改了什么、怎么验证的、实测环境；
4. 涉及界面 / 翻译 / 启动的改动，附上截图或日志片段。

「欢迎认领」的 issue 会写清**从哪个文件开始、怎么验收**；做完在 README 的贡献者名单里署名。
