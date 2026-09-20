"""清单守卫：tools/ 下的探针脚本必须在清单里登记，并保持与 README 一致。"""
from __future__ import annotations

import sys

from common import ROOT, Result, load_json, main

MANIFEST = "tools/checks/tools-manifest.json"
PHASES = {"P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "—"}


def check() -> Result:
    result = Result("探针脚本清单")
    manifest = load_json(MANIFEST)
    kinds = set(manifest["kinds"])
    entries = manifest["scripts"]

    listed = [entry["path"] for entry in entries]
    duplicates = sorted({p for p in listed if listed.count(p) > 1})
    if duplicates:
        result.fail(f"清单里有重复登记：{duplicates}")

    for entry in entries:
        path = ROOT / entry["path"]
        if not path.exists():
            result.fail(f"清单登记了不存在的脚本：{entry['path']}")
        if entry["kind"] not in kinds:
            result.fail(f"{entry['path']} 的 kind 非法：{entry['kind']}")
        if entry["phase"] not in PHASES:
            result.fail(f"{entry['path']} 的 phase 非法：{entry['phase']}")
        if not str(entry.get("expected") or "").strip():
            result.fail(f"{entry['path']} 缺少 expected 结论")

    on_disk = sorted(p.relative_to(ROOT).as_posix()
                     for p in (ROOT / "tools").glob("*.py") if p.is_file())
    unlisted = sorted(set(on_disk) - set(listed))
    if unlisted:
        result.fail(f"新增脚本没有登记到清单：{', '.join(unlisted)}")
    gone = sorted(set(listed) - set(on_disk))
    if gone:
        result.fail(f"清单里的脚本已不存在：{', '.join(gone)}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    not_documented = [entry["path"].replace("tools/", "") for entry in entries
                      if entry["kind"] in {"offline", "network", "live", "local-process"}
                      and entry["path"].replace("tools/", "") not in readme]
    if not_documented:
        result.warn(f"README 自检脚本小节未提到：{', '.join(not_documented)}")

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    result.note("脚本分类：" + "，".join(f"{k} {v}" for k, v in sorted(counts.items())))
    result.note(f"共 {len(entries)} 个脚本，全部有 kind / phase / expected")
    return result


if __name__ == "__main__":
    sys.exit(main(check))
