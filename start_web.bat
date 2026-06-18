@echo off
setlocal

cd /d "%~dp0"

set "NO_PROXY=*"
set "HTTP_PROXY="
set "HTTPS_PROXY="

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage_web.ps1" start
if errorlevel 1 (
    echo.
    echo [ERROR] Startup failed. Press any key to close this window.
    pause >nul
    exit /b 1
)

endlocal
