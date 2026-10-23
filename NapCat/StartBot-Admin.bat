@echo off
setlocal
cd /d "%~dp0"
echo [1/2] starting AstrBot (hidden background service) ...
schtasks /run /tn "QQBot-AstrBot" >nul 2>&1
timeout /t 6 /nobreak >nul
echo [2/2] starting NapCat (needs administrator privileges) ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0elevate.ps1"
exit /b 0
