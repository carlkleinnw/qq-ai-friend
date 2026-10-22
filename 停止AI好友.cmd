@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\launch.ps1" -Action Stop
if errorlevel 1 pause
