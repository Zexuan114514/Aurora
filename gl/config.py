"""全局配置与路径管理。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

APP_NAME = "Aurora"
APP_TITLE = "Aurora 游戏启动器"
APP_ID = "aurora-launcher"
VERSION = "1.0.0"

PKG_DIR = Path(__file__).resolve().parent
WEB_DIR = PKG_DIR / "web"
PROJECT_DIR = PKG_DIR.parent


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """程序所在目录：源码运行是项目根目录，打包后是 exe 所在目录。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return PKG_DIR.parent


def _default_data_dir() -> Path:
    """数据目录：优先程序目录，不可写时退回 LOCALAPPDATA。"""
    env = os.environ.get("AURORA_DATA")
    if env:
        return Path(env).expanduser().resolve()

    candidate = app_dir() / "data"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return candidate
    except Exception:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_ID


DATA_DIR = _default_data_dir()
LIBRARY_FILE = DATA_DIR / "library.json"
CACHE_DIR = DATA_DIR / "cache"
STEAM_CACHE_DIR = CACHE_DIR / "steam"
WEB_DATA_DIR = DATA_DIR / "webview"
LOG_FILE = DATA_DIR / "aurora.log"

# 用户素材：原图存在 data/ 下，副本同步到 web/ 供本地 http 服务访问
BG_SOURCE_DIR = DATA_DIR / "backgrounds"
ICON_SOURCE_DIR = DATA_DIR / "icons"
COVER_SOURCE_DIR = DATA_DIR / "covers"
USER_BG_DIR = WEB_DIR / "userbg"
USER_ICON_DIR = WEB_DIR / "usericon"
USER_COVER_DIR = WEB_DIR / "usercovers"

# 默认设置
DEFAULT_SETTINGS = {
    "lang": "schinese",          # Steam 简介语言
    "blur": 30,                  # 毛玻璃模糊强度 px
    "saturation": 190,           # 玻璃饱和度 %
    "scrim": 42,                 # 背景暗化 %
    "accent": "#0A84FF",         # 强调色
    "theme_mode": "dark",        # dark | light | auto（auto 跟随 Windows 应用主题）
    "palette": "aurora",         # aurora | lime | sakura | amber | custom
    "hall_layout": "ring",       # ring（环形队列）| flat（平铺横滑，NS 大厅）
    "auto_search": True,         # 导入后自动联网搜索
    # 简介翻译：LLM 接口为主 + 免费接口兜底
    "translate_enabled": True,                  # 导入后自动翻译简介
    "translate_provider": "auto",               # auto | llm | free
    "translate_base_url": "https://api.deepseek.com",
    "translate_api_key": "",
    "translate_model": "deepseek-chat",
    "translate_target": "zh-CN",
    "show_original": False,      # 前端显示原文（否则显示译文）
    "ken_burns": True,           # 背景缓慢缩放
    "show_playtime": True,
    "close_to_tray": False,      # 关闭窗口时缩到托盘继续后台运行
    # 获取游戏：下载目录监听 + 自动解压
    "download_dir": str(DATA_DIR / "downloads"),   # 专用下载目录，可改
    "download_watch": True,                        # 盯着下载目录，新游戏自动入库
    "download_extract": True,                      # 压缩包自动解压
    # 获取游戏：资源站（点一下用默认浏览器打开，可自己增删）
    "resource_sites": [
        {"id": "site-itch-vn", "name": "itch.io 免费视觉小说",
         "url": "https://itch.io/games/free/tag-visual-novel"},
        {"id": "site-kungal", "name": "kungal",
         "url": "https://www.kungal.com/galgame"},
        {"id": "site-dlsite", "name": "DLsite", "url": "https://www.dlsite.com/"},
    ],
    # 转区启动（Locale Emulator）
    "le_proc_path": "",          # 用户指定的 LEProc.exe（留空则自动探测）
    "locale_default": False,     # 新导入的游戏默认开启转区
    # 网络：代理路线
    "proxy_mode": "auto",        # auto | direct | manual
    "proxy_url": "",             # manual 时的代理地址
    "proxy_fallback": True,      # 走代理失败时自动试一次直连
    # 游戏内翻译（Textractor 钩子 + 屏幕 OCR）
    "vntext_enabled": False,     # 是否开启游戏内翻译
    "vntext_engine": "auto",     # auto | hook | ocr
    "vntext_tractor_path": "",   # 用户指定的 TextractorCLI.exe（留空则自动探测）
    "vntext_auto_start": False,  # 启动游戏时自动开始翻译
    "vntext_context_lines": 4,   # 送给 LLM 的上文句数
    "vntext_max_chars": 1200,    # 超过这个长度的行不翻（多半是噪声）
    "vntext_ocr_interval": 0.9,  # OCR 采样间隔（秒）
    "vntext_overlay": {          # 悬浮窗外观与位置
        "x": 0, "y": 0, "w": 760, "h": 150,
        "font": 20, "opacity": 0.9, "mode": "translated", "click_through": True,
    },
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: 日志超过这个大小就滚动一次（保留 .log.1 一份）
LOG_MAX_BYTES = 512 * 1024
#: 接口缓存最多保留多久（各源自己的 TTL 是 7~30 天，这里只是兜底清理）
CACHE_MAX_AGE = 90 * 24 * 3600


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, STEAM_CACHE_DIR, WEB_DATA_DIR,
              BG_SOURCE_DIR, ICON_SOURCE_DIR, COVER_SOURCE_DIR,
              USER_BG_DIR, USER_ICON_DIR, USER_COVER_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def sync_user_assets() -> None:
    """把用户素材同步进 web 目录。

    打包成单文件 exe 时 web 目录是临时解压目录，每次启动都要重新同步，
    否则用户设置的背景图/自定义图标会失效。
    """
    for src, dst in ((BG_SOURCE_DIR, USER_BG_DIR), (ICON_SOURCE_DIR, USER_ICON_DIR),
                     (COVER_SOURCE_DIR, USER_COVER_DIR)):
        try:
            src.mkdir(parents=True, exist_ok=True)
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if not item.is_file():
                    continue
                target = dst / item.name
                if not target.exists() or target.stat().st_mtime < item.stat().st_mtime:
                    shutil.copy2(item, target)
        except Exception as exc:
            log(f"sync user assets failed: {exc}")


def log(message: str) -> None:
    try:
        ensure_dirs()
        import datetime

        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def prune_log() -> None:
    """日志超过上限时滚动到 aurora.log.1，避免无限增长。"""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            backup = LOG_FILE.with_name(LOG_FILE.name + ".1")
            try:
                if backup.exists():
                    backup.unlink()
            except OSError:
                pass
            os.replace(LOG_FILE, backup)
    except Exception:
        pass


def prune_cache(max_age: float = CACHE_MAX_AGE) -> int:
    """清掉过期的接口缓存，返回删除的文件数。"""
    removed = 0
    try:
        deadline = time.time() - max_age
        for path in CACHE_DIR.rglob("*.json"):
            try:
                if path.stat().st_mtime < deadline:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    except Exception:
        pass
    return removed


def read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
