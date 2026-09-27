# ADR-0003：运行时零新增依赖

## 状态

已接受。

## 背景

当前运行时依赖只有 `pywebview` 与 winrt 投影包（Windows OCR），其余全部是标准库 + ctypes。
单文件 exe 通过 PyInstaller 打包，并在脚本里显式排除 numpy/pandas/tkinter 等重量级包。

## 决策驱动

- 分发体积与启动速度（D4）。
- 供应链与许可可控（用户机上的杀毒误报、依赖审计）。
- 架构目标可以通过自研小内核达成：TaskRunner、EventBus、Protocol 端口、AST 守卫、JSON 迁移器。

## 考虑过的选项

1. **运行时零新增依赖**（开发期可加 pytest 等工具）。
2. **少量成熟库**（pydantic / diskcache / structlog）。
3. **框架级依赖**（DI 容器、FastAPI 侧车）。

## 决定

选择 **1**。开发期允许 `pytest`（放进 `requirements-dev.txt`，不进发布包）；运行时代码禁止新增第三方依赖，
需要的能力用标准库实现（`concurrent.futures` / `queue` / `threading` / `http.server` / `json` / `ast` / `importlib`）。

### 依赖清单的固定版本

`requirements.txt` 把实测过的运行环境固定下来：`pywebview==6.2.1`、`pythonnet==3.1.0`、
`winrt-*==3.2.1`。其中 **pythonnet 不是新增依赖** —— pywebview 在 Windows 上自身要求它
（`Requires-Dist: pythonnet; sys_platform == "win32"`）；显式列出只为让本地、CI 和发布包用同一种运行环境，
`tools/build_exe.py` 在开始打包前会断言这两个版本，版本不符就直接报错而不是产出一个可疑的 exe。
`tools/checks/check_dependencies.py` 的 requirements 白名单相应放行 `pythonnet`，其余新增依赖仍会被拦下。

## 后果

- ✅ 打包体积、启动路径、许可与安全面保持可控。
- ✅ 离线测试不依赖外部服务（fake 适配器即可）。
- ⚠️ 需要自研一些基础设施（迁移器、事件总线、HTTP 静态服务），必须把这部分代码控制在可审计的规模内。
- ⚠️ 不能使用 pydantic 做契约校验 → 用 schema 校验函数 + 契约快照代替。

## 后续动作

- 在 `tests/` 引入 pytest；在 CI 里跑离线检查。
- 任何「想加库」的诉求先评估：能否用 ≤150 行标准库代码替代；不能替代再立 ADR。
