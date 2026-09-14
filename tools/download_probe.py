"""「获取游戏」自检：资源站增删 / 链接跳转 + 下载目录监听 / 自动解压 / 自动导入。

全部在沙盒里跑（数据目录与下载目录都在 _sandbox 下），
打开链接的动作会被替换成记录 URL，不会真的弹出浏览器。结果写入 UTF-8 报告。
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["AURORA_DATA"] = str(ROOT / "_sandbox" / "download-probe-data")
sys.path.insert(0, str(ROOT))

from gl import downloads  # noqa: E402
from gl.api import Api  # noqa: E402

REPORT = Path(__file__).resolve().parent / "download-report.txt"
SANDBOX = ROOT / "_sandbox" / "download-probe"


def main() -> int:
    out = io.StringIO()
    ok = True

    def write(line: str = "") -> None:
        out.write(line + "\n")

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        if not passed:
            ok = False
        write(f"  {'OK ' if passed else 'BAD'} {label}" + (f"  {detail}" if detail else ""))

    write("Aurora 获取游戏自检")
    write("=" * 52)

    # ---------------- 资源站 ----------------
    write("\n[资源站管理]")
    api = Api()
    opened: list[str] = []
    api.open_url = lambda url: (opened.append(url), {"ok": True})[1]   # 不真的弹浏览器

    defaults = api.list_sites().get("sites") or []
    check("有默认站点", len(defaults) >= 3, "、".join(s["name"] for s in defaults))

    added = api.add_site("自检站点", "https://example.com/search?q={query}")
    check("能添加站点", bool(added.get("ok")), str((added.get("site") or {}).get("name")))
    check("非法地址被拒", not api.add_site("坏站点", "example.com")["ok"])
    check("空名字被拒", not api.add_site("   ", "https://example.com")["ok"])

    site_id = (added.get("site") or {}).get("id")
    api.open_site(site_id, "千恋万花")
    check("模板站点会拼上关键词",
          bool(opened) and "example.com/search?q=%E5%8D%83%E6%81%8B%E4%B8%87%E8%8A%B1" in opened[-1],
          opened[-1] if opened else "(没有打开)")

    plain = api.add_site("无模板站点", "https://example.org/galgame")
    api.open_site((plain.get("site") or {}).get("id"), "千恋万花")
    check("无模板站点原样打开", bool(opened) and opened[-1] == "https://example.org/galgame",
          opened[-1] if opened else "(没有打开)")

    api.remove_site(site_id)
    api.remove_site((plain.get("site") or {}).get("id"))
    left = api.list_sites().get("sites") or []
    check("能删除站点", all(s["id"] not in (site_id,) for s in left), f"剩余 {len(left)} 个")
    check("打开不存在的站点会报错", not api.open_site("nope").get("ok"))

    # ---------------- 下载目录 ----------------
    write("\n[下载目录监听]")
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True, exist_ok=True)
    settings = {"download_dir": str(SANDBOX), "download_watch": True,
                "download_extract": True}
    imported: list[str] = []
    events: list[dict] = []
    watcher = downloads.DownloadWatcher(
        settings_getter=lambda: settings,
        save_setting=lambda key, value: None,
        import_fn=lambda paths: (imported.extend(paths), len(paths))[1],
        status_fn=events.append,
        interval=0.2,
    )
    first = watcher.poll_once()
    check("首次扫描只建基线、不回溯导入", first.get("skipped") == "baseline", str(first))

    archive = SANDBOX / "测试游戏.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("测试游戏/start.exe", b"MZ-fake")
        zf.writestr("测试游戏/data/readme.txt", "hello")
    watcher.poll_once()                 # 第一次：可能还在写
    time.sleep(0.05)
    second = watcher.poll_once()        # 第二次：稳定后处理
    check("下载稳定后自动处理", bool(second.get("handled")), str(second.get("handled")))
    check("自动解压出游戏文件夹", (SANDBOX / "测试游戏").is_dir())
    check("不会套娃（同名顶层目录被摊平）",
          (SANDBOX / "测试游戏" / "start.exe").is_file()
          and not (SANDBOX / "测试游戏" / "测试游戏").exists())
    check("导入回调收到路径", bool(imported), str([Path(p).name for p in imported]))
    check("原始压缩包保留", archive.exists())
    kinds = [e.get("kind") for e in events]
    check("发出了解压 / 导入事件", "extracted" in kinds and "imported" in kinds, str(kinds))

    write("\n[手动扫描]")
    exe = SANDBOX / "直接放的.exe"
    exe.write_bytes(b"MZ")
    manual = watcher.scan_now()
    check("手动扫描能导入新文件", bool(manual.get("imported")), str(manual.get("handled")))
    check("已处理过的条目不会重复报",
          "测试游戏.zip" not in (manual.get("handled") or []), str(manual.get("handled")))

    write("\n[解压工具]")
    tool = downloads.find_extractor()
    check("检测到解压工具（.rar/.7z 需要）", tool is not None,
          f"{tool[0]}: {tool[1]}" if tool else "未找到 7-Zip / WinRAR（.zip 仍可解压）")

    write("\n结论: " + ("全部通过" if ok else "存在失败项"))
    text = out.getvalue()
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
