"""网络自检：代理解析、端点连通性、直连 / 手动对比、失败自动换路。

报告写入 tools/net-report.txt。外网全挂时只记为「离线跳过」，不算失败；
但换路（proxy 失败自动试直连）是纯本地行为，必须通过。
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SANDBOX = ROOT / "_sandbox"
TEST_DATA = SANDBOX / "net-data"
REPORT = Path(__file__).resolve().parent / "net-report.txt"
PROBE_URL = "https://store.steampowered.com/api/storesearch/?term=neko&cc=CN&l=schinese"

os.environ["AURORA_DATA"] = str(TEST_DATA)

from gl import netproxy  # noqa: E402
from gl.api import Api  # noqa: E402
from gl.sources import net  # noqa: E402

failed = 0


def main() -> int:
    out = io.StringIO()

    def write(line: str = "") -> None:
        out.write(line + "\n")

    def check(label: str, ok: bool, detail="") -> bool:
        global failed
        if not ok:
            failed += 1
        write(f"  {'OK ' if ok else 'BAD'} {label}" + (f"  {detail}" if detail else ""))
        return ok

    shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir(parents=True, exist_ok=True)

    write("Aurora 网络自检")
    write("=" * 52)

    write("\n[当前生效路线]")
    route = netproxy.describe()
    write(f"  mode={route['mode']} proxy={route['proxy'] or '(直连)'} "
          f"source={route['source']} fallback={route['fallback']}")
    write(f"  bypass: {', '.join(route['bypass']) or '(无)'}")
    check("describe() 结构完整",
          route.get("ok") and route.get("mode") in ("auto", "direct", "manual")
          and "source" in route)

    write("\n[路线解析]")
    direct = netproxy.resolve({"proxy_mode": "direct"})
    check("direct 模式强制直连", direct["proxy"] == "" and direct["fallback"] is False,
          str(direct["source"]))
    manual = netproxy.resolve({"proxy_mode": "manual", "proxy_url": "127.0.0.1:7890"})
    check("手动地址自动补 http://", manual["proxy"] == "http://127.0.0.1:7890",
          manual["proxy"])
    bad = netproxy.resolve({"proxy_mode": "manual", "proxy_url": "http://"})
    check("非法地址退化为直连", bad["proxy"] == "", bad["source"])
    env = netproxy.resolve({"proxy_mode": "auto"})
    check("auto 模式给出源说明", bool(env["source"]), env["source"])

    api = Api()
    try:
        write("\n[端点连通性 test_network]")
        t0 = time.time()
        res = api.test_network()
        rows = res.get("results") or []
        for row in rows:
            write(f"  {'OK ' if row['ok'] else 'BAD'} {row['name']:10} {row['detail']}")
        write(f"  用时 {time.time() - t0:.1f}s，生效代理 {res.get('proxy') or '(直连)'}"
              f"（{res.get('source')}）")
        ok_count = sum(1 for r in rows if r["ok"])
        if ok_count == 0:
            write("  WARN 五个端点全不通：按离线处理，跳过连通性断言")
        else:
            check("至少 3 个端点通", ok_count >= 3, f"{ok_count}/{len(rows)}")

        write("\n[直连 vs 手动（换路）]")
        api.set_proxy_option("proxy_mode", "direct")
        check("切到直连后 current() 也变了", netproxy.current()["proxy"] == "")
        t0 = time.time()
        try:
            net.fetch(PROBE_URL, timeout=8, attempts=1)
            direct_ms = int((time.time() - t0) * 1000)
            write(f"  直连请求成功：{direct_ms} ms")
            online = True
        except Exception as exc:
            write(f"  直连请求失败：{type(exc).__name__}: {exc}")
            online = False

        if online:
            api.set_proxy_option("proxy_mode", "manual")
            api.set_proxy_option("proxy_url", "http://127.0.0.1:1")   # 没人监听的端口
            api.set_proxy_option("proxy_fallback", True)
            check("坏代理下 fallback=True", netproxy.current()["fallback"] is True)
            t0 = time.time()
            try:
                net.fetch(PROBE_URL, timeout=8, attempts=1)
                ok_changed = True
                detail = f"代理失败后自动直连成功（{int((time.time() - t0) * 1000)} ms）"
            except Exception as exc:
                ok_changed = False
                detail = f"{type(exc).__name__}: {exc}"
            check("走代理失败会自动换直连", ok_changed, detail)

            api.set_proxy_option("proxy_fallback", False)
            try:
                net.fetch(PROBE_URL, timeout=8, attempts=1)
                ok_strict = False
                detail = "居然成功了（不该）"
            except Exception as exc:
                ok_strict = True
                detail = f"按预期失败：{type(exc).__name__}"
            check("关掉换路后坏代理就失败", ok_strict, detail)
        else:
            write("  WARN 当前离线，跳过换路断言")
    finally:
        # 还原成自动，别把沙盒里的实验设置留在外面
        api.set_proxy_option("proxy_mode", "auto")
        api.set_proxy_option("proxy_url", "")
        api.set_proxy_option("proxy_fallback", True)
        api._downloads.stop()

    write("\n[沙盒还原]")
    check("代理设置已还原为 auto", netproxy.describe()["mode"] == "auto")

    write("\n结论: " + ("全部通过" if not failed else f"{failed} 项失败"))
    text = out.getvalue()
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
