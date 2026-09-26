# Aurora 更新日志

公开版本按 `aurora/infra/store/paths.py` 中的 `VERSION` 管理。数据 `SCHEMA_VERSION`、前端私有子包版本和 P8.x 内部里程碑不属于对外版本号。

## [1.0.0] - 首个公开版本（待发布）

详见 [v1.0.0 Release Notes](docs/releases/v1.0.0.md)。

### 新增

- 本地游戏库、资料匹配、分类页、五套主题、转区启动和游戏内逐句翻译悬浮窗。
- 资料源 / 翻译引擎插件接口、引擎规则包和可复现的 Windows 打包流程。

### 改进与修复

- 分类页批量选择和封面操作、翻译面板线程详情、主题控件、悬浮窗和输入框可读性。
- Aurora.exe 写入产品名、公司名、FileVersion 和 ProductVersion。

### 下载与更新

- Release 发布后从 [GitHub Releases](https://github.com/Zexuan114514/Aurora/releases) 下载 `Aurora.exe`。
- Windows 程序未签名，可能出现“未知发布者”提示；更新前请核对 SHA-256。
