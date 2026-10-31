@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0quant_env\Scripts\python.exe" -X utf8 -B "%~dp0K线看盘软件\launch.py"
if errorlevel 1 pause
