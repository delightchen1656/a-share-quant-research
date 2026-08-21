$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ProjectDir\..\quant_env\Scripts\python.exe" "$ProjectDir\run.py" evening
