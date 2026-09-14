@echo off
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
