"""打包成单文件 exe（放到项目根目录的 Aurora.exe）。

用法：
    python tools\\build_exe.py
    python tools\\build_exe.py --dry-run     # 只检查打包输入（CI 用），不调用 PyInstaller

脚本会自动准备 PyInstaller（优先用当前环境，没有就在 _build\\venv 里装一个），
然后用一组固定的参数打包，最后把结果复制到项目根目录。
"""
from __future__ import annotations

# 统一 UTF-8 控制台（说明见 tools/_common.py）
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from _common import setup_console  # noqa: E402

setup_console()

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "_build"
VENV = BUILD / "venv"
DIST = BUILD / "dist"
STAGE = BUILD / "web-stage"
ICON = ROOT / "gl" / "assets" / "aurora.ico"
TARGET = ROOT / "Aurora.exe"

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

# 这些包在 Anaconda 里常被间接扫到，但本项目完全用不上，排除掉能显著减小体积/避免 hook 报错
EXCLUDES = [
    "numpy", "pandas", "matplotlib", "scipy", "PyQt5", "PySide2", "PySide6",
    "tkinter", "IPython", "notebook", "pytest", "sqlalchemy", "cv2", "sphinx",
    "jupyter", "numba", "sympy", "torch", "tensorflow",
]


def python_with_pyinstaller() -> Path | None:
    """返回一个能用 PyInstaller 的 python 解释器。"""
    for candidate in (Path(sys.executable), VENV / "Scripts" / "python.exe"):
        if not candidate.exists():
            continue
        probe = subprocess.run([str(candidate), "-c", "import PyInstaller"],
                               capture_output=True)
        if probe.returncode == 0:
            return candidate
    return None


def ensure_builder() -> Path:
    found = python_with_pyinstaller()
    if found:
        return found
    print("未找到 PyInstaller，正在 _build\\venv 中安装 ...")
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(VENV)],
                   check=True)
    python = VENV / "Scripts" / "python.exe"
    subprocess.run([str(python), "-m", "pip", "install", "--quiet",
                    "--upgrade", "pip", "pyinstaller"], check=True)
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
    if not ICON.is_file():
        problems.append(f"缺少图标：{ICON.relative_to(ROOT)}（先跑 python tools\\make_icon.py）")
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
    return 0


def build(python: Path) -> int:
    if not ICON.exists():
        print("缺少图标，先运行 python tools\\make_icon.py")
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
        "--add-data", f"{web};gl/web",
        "--add-data", f"{ROOT / 'gl' / 'assets'};gl/assets",
        # P6：引擎规则包（内置）随包分发，供 aurora/infra/rules.py 加载
        "--add-data", f"{ROOT / 'aurora' / 'rules'};aurora/rules",
        "--collect-data", "webview",
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
