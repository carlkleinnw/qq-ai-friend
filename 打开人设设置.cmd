@echo off
cd /d "%~dp0"
runtime\conda\python.exe scripts\service.py start --no-browser
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "http://127.0.0.1:6185/#/plugin-view/astrbot_plugin_persona_studio/editor"
