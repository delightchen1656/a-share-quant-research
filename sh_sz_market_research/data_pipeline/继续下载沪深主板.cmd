@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 沪深主板日线下载：2018-01-01 至当前配置日期
echo 支持断点续传，不会覆盖已完成文件。
"..\quant_env\Scripts\python.exe" download_mainboard.py --exchange ALL
set EXIT_CODE=%ERRORLEVEL%
echo.
echo 下载程序结束，退出码：%EXIT_CODE%
pause
exit /b %EXIT_CODE%
