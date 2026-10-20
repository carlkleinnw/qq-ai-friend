@echo off
chcp 65001 >nul
"%~dp0runtime\conda\python.exe" "%~dp0scripts\service.py" start
if errorlevel 1 pause
