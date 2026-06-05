@echo off
setlocal

cd /d "%~dp0"

set "NO_PROXY=*"
set "HTTP_PROXY="
set "HTTPS_PROXY="

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] 未找到虚拟环境：.venv\Scripts\python.exe
    echo 请先确认项目环境已经创建完成。
    pause
    exit /b 1
)

echo.
echo ==========================================
echo   多交易所套利系统页面原型启动中...
echo   访问地址: http://127.0.0.1:8000/login
echo ==========================================
echo.

start "" powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "for ($i = 0; $i -lt 30; $i++) {" ^
  "  try {" ^
  "    $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/login' -UseBasicParsing -TimeoutSec 2;" ^
  "    if ($resp.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8000/login'; break }" ^
  "  } catch {}" ^
  "  Start-Sleep -Seconds 1" ^
  "}"

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

endlocal
