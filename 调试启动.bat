@echo off
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
