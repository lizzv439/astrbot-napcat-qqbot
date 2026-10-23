@echo off
setlocal
chcp 65001 >nul
echo Stopping QQ bot components ...
schtasks /end /tn "QQBot-AstrBot" >nul 2>&1
taskkill /IM python.exe /F >nul 2>&1
taskkill /IM NapCatWinBootMain.exe /F >nul 2>&1
taskkill /IM QQ.exe /F >nul 2>&1
echo Done. AstrBot and NapCat/QQ have been stopped.
timeout /t 3 >nul
