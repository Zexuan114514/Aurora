@echo off
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
