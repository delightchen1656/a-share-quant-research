@echo off
setlocal
cd /d "%~dp0"
title Quant Local Backtest
set "PYTHON=%~dp0local_project\quant_env\Scripts\python.exe"
set "PROJECT=%~dp0local_project"
set "SCRIPT=%~dp0basic_backtest_example\local_backtest.py"
set "OUTPUT=%~dp0basic_backtest_example\output"

if not exist "%PYTHON%" (
  echo Project environment was not found.
  echo Run the one-click environment setup first.
  pause
  exit /b 1
)

if not exist "%PROJECT%\sh_sz_market_research\data_pipeline\data\raw\SH\600000.SH.parquet" (
  echo Market data was not found.
  echo Run the one-click environment setup first.
  pause
  exit /b 1
)

echo Running the local backtest with the default strategy...
"%PYTHON%" "%SCRIPT%" --project-root "%PROJECT%" --output "%OUTPUT%"
set "RESULT=%ERRORLEVEL%"
echo.
if not "%RESULT%"=="0" (
  echo Backtest failed. Read the error above.
  pause
  exit /b %RESULT%
)

echo Backtest completed.
echo Summary: %OUTPUT%\summary.json
echo Trades:  %OUTPUT%\trades.csv
start "" explorer.exe "%OUTPUT%"
pause
exit /b 0
