"""打包成单文件 exe（放到项目根目录的 Aurora.exe）。

用法：
    python tools\\build_exe.py

脚本会自动准备 PyInstaller（优先用当前环境，没有就在 _build\\venv 里装一个），
然后用一组固定的参数打包，最后把结果复制到项目根目录。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "_build"
VENV = BUILD / "venv"
DIST = BUILD / "dist"
ICON = ROOT / "gl" / "assets" / "aurora.ico"
TARGET = ROOT / "Aurora.exe"

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


def build(python: Path) -> int:
    if not ICON.exists():
        print("缺少图标，先运行 python tools\\make_icon.py")
        return 1
    for folder in (DIST, BUILD / "build"):
        shutil.rmtree(folder, ignore_errors=True)
    spec = BUILD / "Aurora.spec"
    spec.unlink(missing_ok=True)

    args = [
        str(python), "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed", "--name", "Aurora",
        "--icon", str(ICON),
        "--add-data", f"{ROOT / 'gl' / 'web'};gl/web",
        "--add-data", f"{ROOT / 'gl' / 'assets'};gl/assets",
        "--collect-data", "webview",
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "webview.platforms.edgechromium",
        "--distpath", str(DIST), "--workpath", str(BUILD / "build"),
        "--specpath", str(BUILD),
        str(ROOT / "main.py"),
    ]
    for name in EXCLUDES:
        args += ["--exclude-module", name]

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
    BUILD.mkdir(parents=True, exist_ok=True)
    return build(ensure_builder())


if __name__ == "__main__":
    raise SystemExit(main())
