"""Aurora 游戏启动器 —— 程序入口。"""
from __future__ import annotations

from aurora.infra.tasks import default_runner

import ctypes
import json
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import webview  # noqa: E402

from aurora.platform import winapi  # noqa: E402
from gl import config  # noqa: E402
from gl.api import Api  # noqa: E402

WINDOW_W, WINDOW_H = 1380, 880
MIN_W, MIN_H = 1040, 660


def free_port() -> int:
    """要一个系统确认空闲的端口给本地页面服务。

    pywebview 在 private_mode=False 时会固定用 42001，多个实例（比如 exe 和源码版）
    同时开着就会抢同一个端口，后启动的那个会把旧实例的页面当自己的显示。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _single_instance() -> bool:
    """确保只有一个实例在运行。"""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW(None, False, "Global\\AuroraGameLauncher_SingleInstance")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _webview2_available() -> bool:
    """检查是否安装了 Edge WebView2 运行时（无则退回 Qt 内核）。"""
    import winreg

    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
    )
    for root, path in roots:
        try:
            with winreg.OpenKey(root, path) as handle:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(handle, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, f"{path}\\{name}") as sub:
                            label = str(winreg.QueryValueEx(sub, "name")[0])
                            winreg.QueryValueEx(sub, "pv")
                    except OSError:
                        continue
                    if "WebView2" in label:
                        return True
        except OSError:
            continue
    return False


def _asset_version() -> str:
    """入口 URL 的版本号。

    必须每次启动都不一样：WebView2 会忽略 no-store，如果只用「最新修改时间」，
    改了 index.html 而其它资源更新时版本号没变，浏览器就会复用磁盘缓存里的旧页面。
    """
    latest = 0
    try:
        for path in config.WEB_DIR.rglob("*"):
            if path.is_file() and path.suffix in (".html", ".css", ".js", ".svg"):
                latest = max(latest, int(path.stat().st_mtime))
    except Exception:
        pass
    return f"{latest}-{int(time.time() * 1000)}"


def _check_migration() -> int:
    """`--check-migration`：只报告数据迁移计划，不写任何文件。"""
    from aurora.infra.store import migrations

    try:
        plan = migrations.plan(config.LAYOUT)
    except migrations.MigrationError as exc:
        print(f"迁移无法进行：{exc}")
        return 2
    print("数据迁移检查（--check-migration，未写入任何文件）")
    print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
    if plan.needed:
        print(f"\n执行迁移：直接启动 Aurora（备份会写到 {config.STATE_BACKUP_DIR}）")
    else:
        print("\n无需迁移。")
    return 0


def _drop_listeners() -> int:
    """pywebview 已注册的 drop 监听数量（读不到时返回 -1）。"""
    try:
        from webview.dom import _dnd_state

        return int(_dnd_state.get("num_listeners") or 0)
    except Exception:
        return -1


def bind_file_drop(window: webview.Window, api: Api) -> None:
    """把从资源管理器拖进窗口的文件/文件夹接到导入流程。

    路径由 pywebview 的 DOM 事件提供（WebView2 下只有这条路能拿到真实路径），
    因此必须通过 window.dom 注册监听，而不是在页面里写 JS 监听。

    loaded / shown 可能并发触发，注册必须是幂等的，否则一次拖放会被处理两次。
    """
    state = {"bound": False, "busy": False}
    lock = threading.Lock()

    def on_drop(event: dict) -> None:
        try:
            payload = (event or {}).get("dataTransfer") or {}
            files = payload.get("files") or []
            paths = [f.get("pywebviewFullPath") for f in files if isinstance(f, dict)]
            paths = [p for p in paths if p]
            if not paths:
                return
            api.import_dropped(paths)
        except Exception:
            config.log("drop handling failed:\n" + traceback.format_exc())

    def attempt() -> bool:
        with lock:
            if state["bound"] or state["busy"]:
                return state["bound"]
            if _drop_listeners() > 0:
                # 已经注册过（例如上一次 attempt 成功但没记上）
                state["bound"] = True
                return True
            state["busy"] = True
        try:
            window.dom.body.on("drop", on_drop)
        except Exception:
            config.log("file drop bind failed:\n" + traceback.format_exc())
        finally:
            with lock:
                state["busy"] = False
        if _drop_listeners() != 0:
            with lock:
                state["bound"] = True
            config.log("file drop listener bound")
            return True
        config.log("file drop listener not bound yet")
        return False

    def bind(*_args) -> None:
        attempt()

    window.events.loaded += bind
    window.events.shown += bind

    def retry() -> None:
        for _ in range(6):
            time.sleep(1.0)
            if state["bound"] or attempt():
                return

    default_runner().spawn("appshell.drop_bind", retry, thread_name="aurora-drop-bind")


def _focus_running_instance() -> bool:
    """第二次启动时，把已经在运行的窗口拉到前台。"""
    if winapi.focus_window(winapi.find_window(config.APP_TITLE)):
        config.log("another instance is running; focused it")
        return True
    config.log("another instance is already running; exiting")
    return False


# --------------------------------------------------------------------------- #
# 托盘（可选）：关窗后继续在后台待命，游戏不会被打断
# --------------------------------------------------------------------------- #
def _make_tray(window: webview.Window, api: Api, holder: dict) -> bool:
    from gl.tray import TrayIcon

    def show() -> None:
        try:
            window.show()
            winapi.focus_window(winapi.handle_of(window))
        except Exception as exc:
            config.log(f"tray show failed: {exc}")

    def quit_app() -> None:
        holder["quitting"] = True
        try:
            if holder.get("tray") is not None:
                holder["tray"].stop()
        except Exception:
            pass
        try:
            window.destroy()
        except Exception as exc:
            config.log(f"tray quit failed: {exc}")

    icon = TrayIcon(config.PKG_DIR / "assets" / "aurora.ico", config.APP_TITLE,
                    show, quit_app)
    if not icon.start():
        return False
    holder["tray"] = icon
    api.set_tray(icon)
    return True


def _tray_supervisor(window: webview.Window, api: Api, holder: dict) -> None:
    """跟着设置里的开关，随时把托盘图标建好或撤掉。"""
    while True:
        time.sleep(5)
        try:
            want = bool(api._library.settings.get("close_to_tray"))
            icon = holder.get("tray")
            if want and (icon is None or not icon.alive):
                if icon is not None:
                    holder["tray"] = None
                    api.set_tray(None)
                _make_tray(window, api, holder)
            elif not want and icon is not None:
                icon.stop()
                holder["tray"] = None
                api.set_tray(None)
        except Exception as exc:
            config.log(f"tray supervisor: {exc}")


def bind_tray(window: webview.Window, api: Api) -> dict:
    holder: dict = {"tray": None, "quitting": False}

    def on_closing() -> bool:
        # 返回 False 表示取消关闭 —— 缩到托盘而不是退出
        if holder["quitting"]:
            return True
        return not api.minimize_to_tray()

    window.events.closing += on_closing
    default_runner().spawn("appshell.tray_supervisor", _tray_supervisor, window, api, holder,
                           thread_name="aurora-tray-supervisor")
    return holder


def build_window(api: Api) -> webview.Window:
    entry = f"{config.WEB_DIR / 'index.html'}?v={_asset_version()}"
    return webview.create_window(
        config.APP_TITLE,
        url=entry,
        js_api=api,
        width=WINDOW_W,
        height=WINDOW_H,
        min_size=(MIN_W, MIN_H),
        frameless=True,
        easy_drag=False,
        shadow=True,
        resizable=True,
        background_color="#05050A",
        text_select=True,
        zoomable=False,
        confirm_close=False,
    )


def main() -> int:
    if "--check-migration" in sys.argv:
        return _check_migration()
    config.ensure_dirs()
    config.prune_log()
    config.sync_user_assets()
    if config.prune_cache():
        config.log("pruned expired cache files")
    if not _single_instance():
        _focus_running_instance()
        return 0

    api = Api()
    window = build_window(api)
    api._window = window
    bind_file_drop(window, api)
    bind_tray(window, api)
    # 主窗口关掉后：收走悬浮窗 + 落盘并关停存储写线程
    def on_closed() -> None:
        try:
            api.close_overlay()
        finally:
            api.shutdown()

    window.events.closed += on_closed

    state = {"polished": False}

    def polish(*_args) -> None:
        if state["polished"]:
            return
        mode = str(api._library.settings.get("theme_mode") or "dark")
        dark = mode == "dark" or (mode == "auto" and not winapi.system_prefers_light())
        if winapi.polish(window, dark=dark):
            state["polished"] = True

    window.events.loaded += polish
    window.events.shown += polish

    # 优先用 Edge WebView2 内核（Chromium 新版本，毛玻璃与 color-mix 支持最好）
    order = ["edgechromium", "qt"] if _webview2_available() else ["qt"]
    last_error: Exception | None = None
    for gui in order:
        config.log(f"starting with gui={gui}")
        try:
            webview.start(
                gui=gui,
                debug=bool(os.environ.get("AURORA_DEBUG")),
                private_mode=False,
                http_port=free_port(),
                storage_path=str(config.WEB_DATA_DIR),
            )
            return 0
        except Exception as exc:  # pragma: no cover
            last_error = exc
            config.log(f"gui={gui} failed:\n" + traceback.format_exc())
    if last_error:
        raise last_error
    return 0


if __name__ == "__main__":
    sys.exit(main())
