param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$Bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Push-Location $Target
try {
    py -3.10 -m venv quant_env
    & .\quant_env\Scripts\python.exe -m pip install --upgrade pip
    & .\quant_env\Scripts\python.exe -m pip install -r (Join-Path $Bundle 'environment\requirements.core.lock.txt')
    & .\quant_env\Scripts\python.exe -c "import numpy,pandas,sklearn,lightgbm,baostock,akshare,pyarrow; print('Environment import check passed')"
} finally { Pop-Location }
