@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
set "NAPCAT_PATCH_PACKAGE=%cd%\qqnt.json"
set "NAPCAT_LOAD_PATH=%cd%\loadNapCat.js"
set "NAPCAT_INJECT_PATH=%cd%\NapCatWinBootHook.dll"
set "NAPCAT_MAIN_PATH=%cd%\napcat.mjs"
echo ==========================================================
echo  NapCat QQ Bot  (OneBot v11)
echo  WebUI  : http://127.0.0.1:6099/webui   token: see config\webui.json
echo  Keep this window open. Close it to stop NapCat.
echo ==========================================================
echo.
echo Starting NapCat ...
"%~dp0NapCatWinBootMain.exe" "D:\QQ.exe" "%NAPCAT_INJECT_PATH%"
echo.
echo NapCat boot exited with code %ERRORLEVEL%.
timeout /t 600 /nobreak >nul
