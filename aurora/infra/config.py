"""全局配置与路径管理（P3.9-g 从 gl/config.py 搬入）：路径常量、默认设置、JSON 读写、日志。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from aurora.infra.store import paths as store_paths

APP_NAME = store_paths.APP_NAME
APP_TITLE = store_paths.APP_TITLE
APP_ID = store_paths.APP_ID
VERSION = store_paths.VERSION

# P3.9-g 修正：config 搬进 aurora/infra 后不能再用 __file__ 的 parent（那会指到 aurora/infra），
# 必须从项目根推导；PKG_DIR 保持原语义（gl/ 目录，web 与 assets 所在处）。
PROJECT_DIR = Path(__file__).resolve().parents[2]
PKG_DIR = PROJECT_DIR / "gl"
WEB_DIR = PKG_DIR / "web"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出的 exe 里。"""
    return store_paths.is_frozen()


def app_dir() -> Path:
    """程序所在目录：源码运行是项目根目录，打包后是 exe 所在目录。"""
    return store_paths.app_dir()


# 路径的唯一真相在 aurora/infra/store/paths.py（P2）；这里只是兼容性的同名常量。
LAYOUT = store_paths.default_layout()
DATA_DIR = LAYOUT.root

#: v2 状态文件
STATE_DIR = LAYOUT.state
STATE_BACKUP_DIR = LAYOUT.backup
SETTINGS_FILE = LAYOUT.settings_file
LIBRARY_STATE_FILE = LAYOUT.library_file
SESSIONS_FILE = LAYOUT.sessions_file
VNTEXT_DIR = LAYOUT.vntext
GLOSSARY_FILE = LAYOUT.glossary_file

#: v1 路径（迁移输入 / 老工具兼容）
LIBRARY_FILE = LAYOUT.legacy_library
LEGACY_GLOSSARY_FILE = LAYOUT.legacy_glossary
LEGACY_LOG_FILE = DATA_DIR / "aurora.log"

CACHE_DIR = LAYOUT.cache
STEAM_CACHE_DIR = CACHE_DIR / "steam"
WEB_DATA_DIR = LAYOUT.webview
LOG_FILE = LAYOUT.log_file

# 用户素材：原图存在 data/ 下，由本地静态服务按 /assets/<mount>/… 暴露（P5，ADR-0005）
BG_SOURCE_DIR = LAYOUT.backgrounds
ICON_SOURCE_DIR = LAYOUT.icons
COVER_SOURCE_DIR = LAYOUT.covers

#: 静态服务的挂载表：URL 前缀 → 数据目录（只读，不复制）
ASSET_MOUNTS = {
    "backgrounds": BG_SOURCE_DIR,
    "covers": COVER_SOURCE_DIR,
    "icons": ICON_SOURCE_DIR,
}

# 默认设置
DEFAULT_SETTINGS = {
    "lang": "schinese",          # Steam 简介语言
    "blur": 30,                  # 毛玻璃模糊强度 px
    "saturation": 190,           # 玻璃饱和度 %
    "scrim": 42,                 # 背景暗化 %
    "accent": "#0A84FF",         # 强调色
    "theme_mode": "dark",        # dark | light | auto（auto 跟随 Windows 应用主题）
    "palette": "aurora",         # aurora | lime | sakura | amber | custom
    # v2 起风格与明暗分开存：theme = 风格（aurora | gallery | screening | shelf），
    # theme_mode = 明暗（见 ADR-0013）。v1 前端不读 theme，忽略即可。
    "theme": "aurora",
    "hall_layout": "list",       # list（大图 + 侧列表，v2 默认）| ring（环形队列）| flat（平铺横滑）
    # 背景：默认跟着当前游戏走；也可以钉一张常驻图（P8.4，只支持一张）
    "background_mode": "game",   # game（跟随当前游戏）| custom（常驻图）
    "background_custom": "",     # 常驻图 URL：assets/backgrounds/persistent-*.jpg
    "background_custom_scale": 1.0,   # 常驻图缩放（1.0–3.0）
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
    store_paths.ensure_dirs(LAYOUT)
    for d in (STEAM_CACHE_DIR, BG_SOURCE_DIR, ICON_SOURCE_DIR, COVER_SOURCE_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    _migrate_legacy_log()


def _migrate_legacy_log() -> None:
    """v1 的 data/aurora.log 搬到 data/logs/aurora.log（只搬一次，不删数据）。"""
    try:
        if LEGACY_LOG_FILE.exists() and not LOG_FILE.exists():
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            os.replace(LEGACY_LOG_FILE, LOG_FILE)
            backup = LEGACY_LOG_FILE.with_name(LEGACY_LOG_FILE.name + ".1")
            if backup.exists():
                os.replace(backup, LOG_FILE.with_name(LOG_FILE.name + ".1"))
    except Exception:
        pass


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
