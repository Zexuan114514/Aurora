"""打包成单文件 exe（放到项目根目录的 Aurora.exe）。

用法：
    python tools\\build_exe.py
    python tools\\build_exe.py --dry-run     # 只检查打包输入（CI 用），不调用 PyInstaller

脚本会自动准备 PyInstaller 与 Pillow（优先用当前环境，没有就在 _build\\venv 里安装），
然后用一组固定的参数打包，最后把结果复制到项目根目录。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent))
from _common import setup_console  # noqa: E402

setup_console()

import os
import shutil
import subprocess
import sys
from pathlib import Path

from aurora.infra.store.paths import APP_NAME, VERSION

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "_build"
VENV = BUILD / "venv"
DIST = BUILD / "dist"
STAGE = BUILD / "web-stage"
ICON = ROOT / "gl" / "assets" / "aurora.ico"
ICON_SOURCE = ROOT / "gl" / "assets" / "aurora-icon.png"
TARGET = ROOT / "Aurora.exe"
VERSION_FILE = ROOT / "tools" / "aurora-version.txt"
# 单文件 bootloader 默认解包到 %TEMP%。部分安全策略会禁止从该目录加载 DLL；
# Aurora 的便携目录本来就需要可写，因此把解包目录放到程序目录的 data/ 下。
# 这也避免把用户素材或临时文件写入系统目录；若把程序放入 Program Files，需改用用户目录安装。
RUNTIME_TMPDIR = r"data\_runtime"

#: 真正要打进 exe 的前端文件。用户素材（背景 / 自定义封面 / 图标）P5 起不进 web 目录，
#: 由 aurora/infra/webserver.py 按 /assets/ 直接服务 data/ 下的原图。
#: P8.9 删 v1 之后 gl/web 顶层不再有散文件 —— 前端全在 v2/ 下（见 ADR-0014）。
WEB_FILES = ()
#: v2/：Vite 产物（index.html + overlay.html + bundle/ 哈希资源 + build-info.json）。
#: 源码在 frontend/，产物随包入库；打包只搬 gl/web/v2。
WEB_MODULE_DIRS = ("v2",)

#: 游戏内翻译用的 Windows OCR 是动态导入的，PyInstaller 扫不到，必须显式声明
WINRT_MODULES = (
    "winrt.windows.media.ocr",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.storage",
    "winrt.windows.globalization",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
)

# 这些模块是运行时真正需要的依赖。只检查 PyInstaller/Pillow 会导致 CI 在
# 缺少 pywebview / WinRT 时仍然生成一个看似成功、实际缺件的 exe。
RUNTIME_MODULES = ("webview", "winrt.windows.media.ocr")

#: 打包环境必须满足的版本。pywebview 的 Windows 后端经 pythonnet 调 .NET，
#: 而 pythonnet 3.1.0 要求 clr_loader>=0.3.1：宿主环境里混进旧版 clr_loader
#: （Anaconda 自带 0.2.7.post0）时，exe 照样打得出来，却在启动时报
#: `Failed to resolve Python.Runtime.Loader.Initialize`。所以探针不只看版本号，
#: 还要真的 `import clr` 走一遍 .NET 初始化。
PINNED_PACKAGES = {"pywebview": "6.2.1", "pythonnet": "3.1.0"}

# 这些包在 Anaconda 里常被间接扫到，但本项目完全用不上，排除掉能显著减小体积/避免 hook 报错
EXCLUDES = [
    "numpy", "pandas", "matplotlib", "scipy", "PyQt5", "PySide2", "PySide6",
    "tkinter", "IPython", "notebook", "pytest", "sqlalchemy", "cv2", "sphinx",
    "jupyter", "numba", "sympy", "torch", "tensorflow",
]


def probe_code() -> str:
    """候选解释器的探针：固定版本 + 真加载 .NET + 运行时要用的模块。"""
    versions = "; ".join(
        f"assert _metadata.version({name!r}) == {version!r}"
        for name, version in PINNED_PACKAGES.items())
    imports = "".join(f"; import {name}" for name in RUNTIME_MODULES)
    return ("import importlib.metadata as _metadata; " + versions
            + "; import clr"          # 真正初始化 .NET，挡住 pythonnet / clr_loader 版本不匹配
            + "; import PyInstaller, PIL" + imports)


def probe(candidate: Path) -> tuple[bool, str]:
    """跑探针，返回 (是否可用, 失败摘要)。"""
    proc = subprocess.run([str(candidate), "-c", probe_code()],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode == 0:
        return True, ""
    lines = [line.strip() for line in (proc.stderr or proc.stdout or "").splitlines()
             if line.strip()]
    return False, (lines[-1] if lines else f"退出码 {proc.returncode}")


def describe(python: Path) -> str:
    """打包日志里记下这套环境到底装了什么，方便事后追。"""
    code = ("import importlib.metadata as _m; "
            "print(' / '.join(f'{p} {_m.version(p)}' for p in "
            "('pywebview', 'pythonnet', 'clr_loader')))")
    proc = subprocess.run([str(python), "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc.stdout.strip() if proc.returncode == 0 else "版本未知"


def python_with_pyinstaller() -> Path | None:
    """返回第一个通过探针的解释器（本机解释器优先，其次 _build\\venv）。"""
    for candidate in (Path(sys.executable), VENV / "Scripts" / "python.exe"):
        if candidate.exists() and probe(candidate)[0]:
            return candidate
    return None


def pip_install(python: Path, *requirements: str) -> None:
    """装依赖时把 pip 的缓存和临时目录都钉死在 _build 下。

    两个实测坑：
      * 本机 pip 缓存涨到 2 GB 后，读缓存这一步会空转 CPU 十几分钟（直接联网
        反而二十秒装完），而且 pip 的构建隔离子进程不继承 `--no-cache-dir`，
        必须用环境变量传下去；
      * 某些环境里 pip 会把 pip-build-env-*/pip-unpack-* 建在当前工作目录，
        把仓库根目录搞脏。
    """
    tmp = BUILD / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = {**os.environ,
           "PIP_NO_CACHE_DIR": "1",
           "PIP_DISABLE_PIP_VERSION_CHECK": "1",
           "TMPDIR": str(tmp), "TEMP": str(tmp), "TMP": str(tmp)}
    subprocess.run([str(python), "-m", "pip", "install", "--quiet",
                    "--disable-pip-version-check", "--no-cache-dir",
                    *requirements], check=True, env=env)


def install_builder_deps(python: Path) -> None:
    """补齐打包依赖。

    不用 `--upgrade`：在带 system-site-packages 的环境里，它会把整个
    Anaconda site-packages 拖进解析，几分钟都跑不完。`clr_loader>=0.3.1`
    必须显式点名 —— pythonnet 已经装好时，pip 不会再回头检查它的依赖。
    """
    if subprocess.run([str(python), "-c", "import PyInstaller, PIL"],
                      capture_output=True).returncode != 0:
        pip_install(python, "pyinstaller", "pillow")
    pip_install(python, "-r", str(ROOT / "requirements.txt"), "clr_loader>=0.3.1")


def recreate_venv() -> Path:
    """重建构建用 venv。

    刻意不加 `--system-site-packages`：宿主环境（例如 Anaconda 里的
    `clr_loader 0.2.7`）会被继承进来，正是 pythonnet 加载失败的老来源。
    """
    if VENV.parent != BUILD or ROOT not in VENV.parents:     # 只允许删 _build\venv
        raise SystemExit(f"拒绝重建意外路径：{VENV}")
    shutil.rmtree(VENV, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    return VENV / "Scripts" / "python.exe"


def ensure_builder() -> Path:
    found = python_with_pyinstaller()
    if found:
        print(f"打包环境：{found}\n  {describe(found)}")
        return found

    for candidate in (Path(sys.executable), VENV / "Scripts" / "python.exe"):
        if candidate.exists():
            print(f"候选解释器不可用：{candidate}\n  {probe(candidate)[1]}")

    python = VENV / "Scripts" / "python.exe"
    if python.exists():
        # 旧环境一旦被宿主 site-packages 污染，pip 的解析会在整套 Anaconda 上
        # 空转（实测 CPU 打满十几分钟还没结束）。这种情况直接重建更省事。
        print("现有 _build\\venv 未通过探针，重建隔离环境 ...")
    else:
        print("正在创建 _build\\venv（隔离环境）并安装打包依赖 ...")
    python = recreate_venv()
    install_builder_deps(python)
    ok, reason = probe(python)
    if not ok:
        raise SystemExit(f"打包环境不可用，已停止打包：{reason}")
    print(f"打包环境：{python}\n  {describe(python)}")
    return python


def stage_web() -> Path:
    """把前端源码复制到干净的暂存目录，避免把用户素材一起打进 exe。"""
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    for name in WEB_FILES:
        source = ROOT / "gl" / "web" / name
        if not source.is_file():
            raise FileNotFoundError(f"缺少前端文件：{source}")
        shutil.copy2(source, STAGE / name)
    for name in WEB_MODULE_DIRS:     # ES 模块树（不含用户素材）
        source = ROOT / "gl" / "web" / name
        if not source.is_dir():
            raise FileNotFoundError(f"缺少前端模块目录：{source}")
        shutil.copytree(source, STAGE / name)
    return STAGE


def refresh_explorer_icon(path: Path) -> None:
    """通知 Windows Shell 已替换同路径的 EXE，清除旧图标缓存。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        notify = ctypes.windll.shell32.SHChangeNotify
        notify.argtypes = (ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        notify.restype = None
        name = ctypes.create_unicode_buffer(str(path.resolve()))
        # 让 Shell 丢弃旧的图标/缩略图缓存；不重启资源管理器。
        notify(0x08000000, 0x0000 | 0x1000, None, None)
        # SHCNE_UPDATEITEM / SHCNE_UPDATEDIR + SHCNF_PATHW + SHCNF_FLUSH。
        notify(0x00002000, 0x0005 | 0x1000, ctypes.cast(name, ctypes.c_void_p), None)
        folder = ctypes.create_unicode_buffer(str(path.parent.resolve()))
        notify(0x00001000, 0x0005 | 0x1000, ctypes.cast(folder, ctypes.c_void_p), None)
    except OSError as exc:
        print(f"资源管理器图标缓存刷新失败（不影响打包）：{exc}")


def dry_run() -> int:
    """`--dry-run`：不装 PyInstaller、不打包，只证明「打进包里的东西都在」。"""
    problems: list[str] = []
    for name in WEB_FILES:
        path = ROOT / "gl" / "web" / name
        if not path.is_file():
            problems.append(f"缺少前端文件：gl/web/{name}")
    for name in WEB_MODULE_DIRS:
        folder = ROOT / "gl" / "web" / name
        if not folder.is_dir():
            problems.append(f"缺少前端模块目录：gl/web/{name}")
        elif not any(p.is_file() for p in folder.rglob("*.js")):
            problems.append(f"前端模块目录里没有 js：gl/web/{name}")
    if not ICON_SOURCE.is_file():
        problems.append(f"缺少图标源文件：{ICON_SOURCE.relative_to(ROOT)}")
    if not ICON.is_file():
        problems.append(f"缺少图标：{ICON.relative_to(ROOT)}（先跑 python tools\\make_icon.py）")
    if not VERSION_FILE.is_file():
        problems.append(f"缺少 Windows 版本资源：{VERSION_FILE.relative_to(ROOT)}")
    rules = ROOT / "aurora" / "rules" / "engines"
    if not any(rules.glob("*.json")):
        problems.append("缺少内置引擎规则包：aurora/rules/engines/*.json")
    for module in ("main.py", "aurora/infra/webserver.py", "aurora/infra/rules.py",
                   "aurora/infra/plugins.py"):
        if not (ROOT / module).is_file():
            problems.append(f"缺少运行时文件：{module}")
    if not WINRT_MODULES:
        problems.append("WINRT_MODULES 清单为空（OCR 会缺件）")
    if problems:
        print("打包输入检查未通过：")
        for row in problems:
            print(f"  - {row}")
        return 1
    modules = sum(1 for folder in WEB_MODULE_DIRS
                  for _ in (ROOT / "gl" / "web" / folder).rglob("*.js"))
    print("打包输入检查通过（dry-run，未调用 PyInstaller）：")
    print(f"  前端：{len(WEB_FILES)} 个顶层文件 + {modules} 个模块文件")
    print(f"  图标：{ICON.relative_to(ROOT)}")
    print(f"  规则包：aurora/rules/engines（{len(list(rules.glob('*.json')))} 个）")
    print(f"  动态声明：winrt {len(WINRT_MODULES)} 个模块 + webview 两个平台后端")
    print(f"  解包目录：{RUNTIME_TMPDIR}（应用数据目录）")
    print(f"  版本资源：{APP_NAME} {VERSION}（{VERSION_FILE.relative_to(ROOT)}）")
    return 0


def build(python: Path) -> int:
    # 每次打包都从项目内的 PNG 重建图标，避免使用过期的 ICO。
    icon_result = subprocess.run([str(python), str(ROOT / "tools" / "make_icon.py")], cwd=str(ROOT))
    if icon_result.returncode != 0:
        print("图标生成失败")
        return 1
    for folder in (DIST, BUILD / "build"):
        shutil.rmtree(folder, ignore_errors=True)
    spec = BUILD / "Aurora.spec"
    spec.unlink(missing_ok=True)
    web = stage_web()

    args = [
        str(python), "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "Aurora",
        "--icon", str(ICON),
        "--version-file", str(VERSION_FILE),
        "--runtime-tmpdir", RUNTIME_TMPDIR,
        "--add-data", f"{web};gl/web",
        "--add-data", f"{ROOT / 'gl' / 'assets'};gl/assets",
        # P6：引擎规则包（内置）随包分发，供 aurora/infra/rules.py 加载
        "--add-data", f"{ROOT / 'aurora' / 'rules'};aurora/rules",
        "--collect-data", "webview",
        # pywebview 的 Windows 后端经 pythonnet 加载 .NET；PyInstaller 默认只带
        # Python.Runtime.dll，缺少 deps.json 时会在冻结程序里报 Loader.Initialize。
        "--collect-all", "pythonnet",
        "--collect-all", "clr_loader",
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "webview.platforms.edgechromium",
        "--distpath", str(DIST), "--workpath", str(BUILD / "build"),
        "--specpath", str(BUILD),
        str(ROOT / "main.py"),
    ]
    for name in EXCLUDES:
        args += ["--exclude-module", name]
    for module in WINRT_MODULES:
        args += ["--hidden-import", module]

    print("开始打包 ...")
    result = subprocess.run(args, cwd=str(ROOT))
    if result.returncode != 0:
        print("打包失败")
        return result.returncode

    produced = DIST / "Aurora.exe"
    if not produced.exists():
        print("没有生成 Aurora.exe")
        return 1
    shutil.copy2(produced, TARGET)
    refresh_explorer_icon(TARGET)
    print(f"\n完成：{TARGET}  ({TARGET.stat().st_size / 1024 / 1024:.1f} MB)")
    print("直接双击即可运行，数据保存在同目录的 data\\ 下。")
    return 0


def main() -> int:
    if "--dry-run" in sys.argv:
        return dry_run()
    BUILD.mkdir(parents=True, exist_ok=True)
    return build(ensure_builder())


if __name__ == "__main__":
    raise SystemExit(main())
