@echo off
setlocal

cd /d "%~dp0"

echo.
echo ==========================================
echo   正在重启本地服务...
echo ==========================================
echo.

echo [1/2] 清理 8000 端口占用...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage_web.ps1" cleanup

echo.
echo [2/2] 启动当前项目服务...
start "" cmd /c ""%~dp0start_web.bat""

echo.
echo 已触发重启，请访问: http://127.0.0.1:8000/login

endlocal
