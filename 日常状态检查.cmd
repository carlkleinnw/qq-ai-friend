@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\conda\python.exe" "%~dp0scripts\daily_check.py"
pause
