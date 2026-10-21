@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\conda\python.exe" "%~dp0scripts\native_backup.py" create
pause
