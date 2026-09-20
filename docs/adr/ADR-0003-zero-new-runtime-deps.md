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

## 后果

- ✅ 打包体积、启动路径、许可与安全面保持可控。
- ✅ 离线测试不依赖外部服务（fake 适配器即可）。
- ⚠️ 需要自研一些基础设施（迁移器、事件总线、HTTP 静态服务），必须把这部分代码控制在可审计的规模内。
- ⚠️ 不能使用 pydantic 做契约校验 → 用 schema 校验函数 + 契约快照代替。

## 后续动作

- 在 `tests/` 引入 pytest；在 CI 里跑离线检查。
- 任何「想加库」的诉求先评估：能否用 ≤150 行标准库代码替代；不能替代再立 ADR。
