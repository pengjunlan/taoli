@echo off
setlocal

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0manage_web.ps1" cleanup

endlocal
