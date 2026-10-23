@echo off
setlocal
chcp 65001 >nul
title AstrBot
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
echo ==========================================================
echo  AstrBot v4.29.1
echo  WebUI      : http://127.0.0.1:6185
echo  OneBot v11 : ws://127.0.0.1:6199/ws  (reverse WS server)
echo  Keep this window open. Close it to stop AstrBot.
echo ==========================================================
"%~dp0..\python312\python.exe" "%~dp0main.py"
echo.
echo AstrBot exited with code %errorlevel%
pause
