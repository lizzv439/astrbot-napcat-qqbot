@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
"%~dp0..\python312\python.exe" "%~dp0main.py"
