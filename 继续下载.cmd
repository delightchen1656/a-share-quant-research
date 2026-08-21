@echo off
title A-Share Data Downloader
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0evening_accumulation\continue_download.ps1"
set "DOWNLOAD_EXIT=%ERRORLEVEL%"
echo.
echo Downloader stopped. Exit code: %DOWNLOAD_EXIT%
echo Press any key to close this window.
pause >nul
exit /b %DOWNLOAD_EXIT%
