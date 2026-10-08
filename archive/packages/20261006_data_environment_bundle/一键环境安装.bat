@echo off
setlocal
cd /d "%~dp0"
title Quant Migration One Click Setup
echo This setup uses bundled Python 3.10.11 for the project.
echo Existing Python 3.13 will not be used or removed.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_new_computer.ps1"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" echo Setup failed. Read the error above and run this file again.
if "%RESULT%"=="0" echo Setup completed successfully.
pause
exit /b %RESULT%
