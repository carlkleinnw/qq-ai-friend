@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\launch.ps1" -Action EnableAutostart
if errorlevel 1 pause
