# P0 开源化交付记录

日期：2026-09-27
公开版本：`1.0.0`（唯一来源：`aurora/infra/store/paths.py`）

## 已落地

- 根目录新增 MIT `LICENSE`、`CONTRIBUTING.md`、`CHANGELOG.md`。
- `.gitignore` 纳入 `_compare/`；运行时数据、打包目录和可执行文件继续不入库。
- `README.md` 收敛为产品页，完整的原手册保存在 `docs/manual/README.md`。
- README 明确游戏内翻译是 Aurora 置顶悬浮窗，中文不会直接写入游戏原生文本框。
- 前端 `package.json` / lockfile 跟随公开版本 `1.0.0`；`SCHEMA_VERSION` 和 P8.x 继续作为内部标记。
- PyInstaller 打包使用 `tools/aurora-version.txt` 注入 `FileVersion`、`ProductVersion`、`ProductName`、`CompanyName`。
- `.github/workflows/release.yml` 支持手动输入 tag；先构建前端，再跑 `run_all.py` 与 pytest，随后打包并上传 `Aurora.exe` 和 SHA-256 校验文件。
- Gal Launcher 参考截图在 `docs/THIRD-PARTY-ASSETS.md` 单独标明用途和 MIT 排除边界。

## 首次发布流程

1. 在默认分支合并本记录及相关 P0 提交。
2. 打开 GitHub Actions → `release` → `Run workflow`，输入 `v1.0.0`。
3. 工作流会检查 tag 与公开版本一致，构建并执行发布门禁。
4. Release 页面应包含 `Aurora.exe`、`Aurora.exe.sha256` 和 [v1.0.0 Release Notes](../releases/v1.0.0.md)。

Windows 程序未签名，Release Notes 必须保留“未知发布者”提示。外部工具 Textractor、Locale Emulator 等由用户自行安装，不由 Aurora 下载或打包。

## 本地核对

- `cd frontend && npm run build`：已完成，产物写入 `gl/web/v2/`。
- `python tools/build_exe.py --dry-run`：已通过，能识别版本资源文件。
- 发布工作流中的完整检查和真实打包在 GitHub Actions 执行。
