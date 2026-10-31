@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0quant_env\Scripts\pythonw.exe" -X utf8 -B "%~dp0沪深实盘工作台\tracker\launch.pyw"
