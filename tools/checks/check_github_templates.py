"""贡献通道守卫（开源化 P1）：issue 表单 / PR 模板 / 贡献与安全文档不能悄悄缺件。

只用标准库扫文本，不做完整 YAML 解析（离线检查不许引第三方依赖）：

  * `.github/ISSUE_TEMPLATE/` 下四份表单都在，且都有 `name` / `description` / `body`；
  * 问题反馈表单里的「诊断包」是必填（这是相对同类项目最省事的一条规矩）；
  * 引擎实测规则表单覆盖指纹字段（exe 文件名 / 字节数 / CRC32 / H-code）并指向导出入口；
  * PR 模板提醒三条门禁（run_all / pytest / 前端构建）；
  * CONTRIBUTING / SECURITY / CODE_OF_CONDUCT 在位，且 CONTRIBUTING 提到三个坑。
"""
from __future__ import annotations

import re
import sys

from common import ROOT, Result, main, read_text

TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"
ISSUE_FORMS = ("bug_report.yml", "feature_request.yml", "engine-rule.yml")
_ENTRY = re.compile(r"^  - type: ", re.M)


def _issue_form_entries(text: str) -> list[dict]:
    """把 issue 表单按 `- type:` 切成若干块，取出每块的 id 与是否必填。"""
    chunks = _ENTRY.split(text)[1:]
    entries: list[dict] = []
    for chunk in chunks:
        ident = re.search(r"^\s+id:\s*([A-Za-z0-9_\-]+)\s*$", chunk, re.M)
        required = bool(re.search(r"^\s+required:\s*true\s*$", chunk, re.M))
        if ident:
            entries.append({"id": ident.group(1), "required": required})
    return entries


def check() -> Result:
    result = Result("贡献通道（issue / PR 模板）")

    missing = [name for name in (*ISSUE_FORMS, "config.yml")
               if not (TEMPLATES / name).is_file()]
    if missing:
        result.fail(f".github/ISSUE_TEMPLATE 缺文件：{', '.join(missing)}")
        return result

    for name in ISSUE_FORMS:
        text = read_text(f".github/ISSUE_TEMPLATE/{name}")
        for key in ("name:", "description:", "body:"):
            if not re.search(rf"^{key}", text, re.M):
                result.fail(f"{name} 缺 `{key}`（GitHub 会拒绝加载这份表单）")

    bug = read_text(".github/ISSUE_TEMPLATE/bug_report.yml")
    bug_fields = {row["id"]: row["required"] for row in _issue_form_entries(bug)}
    if not bug_fields.get("diagnostics"):
        result.fail("bug_report.yml 里的「诊断包」字段必须是必填"
                    "（否则又会退化成一轮轮问答）")
    else:
        result.note("问题反馈强制附诊断包：必填字段 " + ", ".join(
            name for name, required in bug_fields.items() if required))

    engine = read_text(".github/ISSUE_TEMPLATE/engine-rule.yml")
    engine_fields = {row["id"] for row in _issue_form_entries(engine)}
    need = {"game", "engine", "exe_name", "exe_size", "crc32", "hook_code", "sample"}
    lost = sorted(need - engine_fields)
    if lost:
        result.fail(f"engine-rule.yml 少了对准 hooks.json schema 的字段：{', '.join(lost)}")
    if "导出我的引擎规则" not in engine:
        result.fail("engine-rule.yml 未指向「设置 → 关于 → 导出我的引擎规则」入口")
    else:
        result.note(f"引擎规则表单字段齐备（{len(engine_fields)} 项），并指向导出入口")

    pr = read_text(".github/PULL_REQUEST_TEMPLATE.md")
    for token, why in (("run_all.py", "离线检查"), ("pytest", "回归测试"),
                       ("npm run build", "前端构建产物")):
        if token not in pr:
            result.fail(f"PR 模板没有提醒跑{why}（{token}）")

    for name in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"):
        if not (ROOT / name).is_file():
            result.fail(f"根目录缺 {name}（开源化 P1 的贡献路径/安全边界/行为准则）")

    contributing = read_text("CONTRIBUTING.md") if (ROOT / "CONTRIBUTING.md").is_file() else ""
    for token, why in (("GBK", "bat 脚本的编码坑"), ("npm run build", "前端构建"),
                       ("run_all.py", "离线检查"), ("pytest", "回归测试"),
                       ("MIT", "inbound=outbound 许可约定")):
        if token not in contributing:
            result.fail(f"CONTRIBUTING.md 没写{why}（缺 `{token}`）")

    security = read_text("SECURITY.md") if (ROOT / "SECURITY.md").is_file() else ""
    if "插件" not in security:
        result.fail("SECURITY.md 没写插件的信任模型（插件与 Aurora 同进程同权限）")
    else:
        result.note("贡献文档齐备：三条路径 + 三个坑；SECURITY 写清插件信任边界")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
