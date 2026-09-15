@echo off
cd /d "%~dp0..\sh_sz_market_research\data_pipeline"
start "" "..\..\quant_env\Scripts\pythonw.exe" dashboard_server.py
exit /b 0
