@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================================
echo   QQ Bot Launcher  (NapCat + AstrBot)
echo ==========================================================
echo.
call "%~dp0NapCat\StartBot-Admin.bat"
echo.
echo AstrBot WebUI : http://127.0.0.1:6185
echo NapCat WebUI  : http://127.0.0.1:6099/webui
echo.
pause
