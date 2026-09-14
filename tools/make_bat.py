"""生成编码正确（GBK + CRLF）的批处理启动脚本。

cmd.exe 按系统 ANSI 代码页解析 .bat，且要求 CRLF 换行；
UTF-8/LF 会让中文被拆成乱码并切断命令行。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RUN = r"""@echo off
chcp 936 >nul
rem ============================================================
rem  Aurora 游戏启动器 —— 双击即可运行（不显示控制台窗口）
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo.
    echo   [X] 没有找到 Python，请先安装 Python 3.9 或更高版本：
    echo       https://www.python.org/downloads/
    echo       安装时请勾选 "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)

%PY% -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   首次运行，正在安装依赖 pywebview ...
    %PY% -m pip install --upgrade pywebview
    if errorlevel 1 (
        echo.
        echo   [X] 依赖安装失败，请手动执行：  %PY% -m pip install pywebview
        echo.
        pause
        exit /b 1
    )
)

%PY% -c "import gl.config" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [X] 程序文件不完整，请在完整目录中运行本脚本。
    echo.
    pause
    exit /b 1
)

set "PYW=pythonw"
where pythonw >nul 2>nul || set "PYW=python"
rem 重定向到 nul：避免子进程继承控制台句柄，双击后控制台会立刻关闭
start "" %PYW% "%~dp0main.py" >nul 2>nul
exit /b 0
"""

DEBUG = r"""@echo off
chcp 936 >nul
rem 调试模式：保留控制台窗口，打印日志与错误
setlocal
cd /d "%~dp0"
set AURORA_DEBUG=1

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo   没有找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

%PY% "%~dp0main.py"
echo.
echo ---- 程序已退出 ----
pause
"""

PACK = r"""@echo off
chcp 936 >nul
rem ============================================================
rem  Aurora 游戏启动器 —— 一键打包成 Aurora.exe
rem  双击本脚本即可：自动准备依赖 + PyInstaller，然后打包
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo.
    echo   [X] 没有找到 Python，请先安装 Python 3.9 或更高版本：
    echo       https://www.python.org/downloads/
    echo       安装时请勾选 "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)

%PY% -c "import gl.config" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [X] 程序文件不完整：请把本脚本放在 Aurora 项目根目录
    echo       （与 main.py、gl 文件夹同级）再运行。
    echo.
    pause
    exit /b 1
)

%PY% -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo.
    echo   正在安装运行依赖 pywebview ...
    %PY% -m pip install --upgrade pywebview
    if errorlevel 1 (
        echo.
        echo   [X] 依赖安装失败，请手动执行：  %PY% -m pip install pywebview
        echo.
        pause
        exit /b 1
    )
)

echo.
echo   正在打包 Aurora.exe ...
echo   首次运行会下载 PyInstaller（几分钟），之后会快很多。
echo.

%PY% "%~dp0tools\build_exe.py"
if errorlevel 1 (
    echo.
    echo   [X] 打包失败：请先看上面的报错。
    echo       也可以双击 调试启动.bat，确认源码本身能正常运行。
    echo.
    pause
    exit /b 1
)

echo.
echo   [OK] 打包完成：%~dp0Aurora.exe
echo        双击它即可运行，数据保存在同目录的 data\ 下。
echo.
pause
exit /b 0
"""


def write(name: str, text: str) -> None:
    path = ROOT / name
    data = text.replace("\n", "\r\n").encode("gbk")
    path.write_bytes(data)
    print(f"written {path}  ({len(data)} bytes, GBK + CRLF)")


def main() -> int:
    write("启动 Aurora.bat", RUN)
    write("调试启动.bat", DEBUG)
    write("打包 Aurora.bat", PACK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
