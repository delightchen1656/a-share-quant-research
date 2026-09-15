@echo off
cd /d "%~dp0"
start "" "..\quant_env\Scripts\pythonw.exe" dashboard_server.py
exit /b 0
