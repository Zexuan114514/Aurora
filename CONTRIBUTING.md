# 参与贡献

感谢你为 Aurora 提交问题、规则包、插件或代码。Aurora 是一个单人维护的 Windows 本地启动器，先把可复现的资料和小而清晰的改动提交进来，维护成本最低。

## 提交前

- 先阅读 [架构文档](docs/architecture/README.md) 和相关 ADR。
- 运行 `python tools\checks\run_all.py`；涉及 Python 时再运行 `python -m pytest`。
- 改动前端后运行 `cd frontend && npm run build`，并提交生成的 `gl/web/v2/` 产物。
- `data/`、`_build/`、`_sandbox/` 和个人诊断文件不应提交。
- `启动 Aurora.bat`、`打包 Aurora.bat`、`调试启动.bat` 由工具生成，中文环境下请保留 GBK + CRLF 格式。

## 贡献方向

1. 在 [引擎规则反馈](docs/engines.md) 中提交可复现的 H-code、样本文本和诊断信息。
2. 按 [插件文档](docs/plugins.md) 编写资料源或翻译引擎插件。
3. 先开 Issue 讨论，再提交核心代码或界面改动。

## 许可

提交代码、文档或规则资料即表示你同意：该贡献可以按本仓库的 MIT License 对外发布。Aurora 之外的第三方软件、商标、截图和图片不因这份许可获得再许可；请在提交素材时说明来源和授权范围。
