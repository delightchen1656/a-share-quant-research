param([switch]$ValidateOnly)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
trap {
    Write-Host ''
    Write-Host "Failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host $_.InvocationInfo.PositionMessage -ForegroundColor DarkRed
    exit 1
}
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = (Resolve-Path (Join-Path $ProjectDir '..\quant_env\Scripts\python.exe')).Path
$RunScript = (Resolve-Path (Join-Path $ProjectDir 'run.py')).Path
$PidFile = Join-Path $ProjectDir 'data\logs\download.pid'

Write-Host 'A-Share historical data resume downloader' -ForegroundColor Cyan
Write-Host "Project: $ProjectDir"

if ($ValidateOnly) {
    Write-Host 'Launcher validation passed.' -ForegroundColor Green
    exit 0
}

if (Test-Path -LiteralPath $PidFile) {
    $OldDownloadPid = [int](Get-Content -LiteralPath $PidFile)
    $OldProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$OldDownloadPid"
    if ($null -ne $OldProcess) {
        $IsExpected = $OldProcess.Name -match '^python(\.exe)?$' -and $OldProcess.CommandLine -like "*$RunScript*download*"
        if (-not $IsExpected) {
            throw "PID $OldDownloadPid is not this project's downloader; refusing to stop it."
        }
        Write-Host "Stopping old downloader PID $OldDownloadPid ..." -ForegroundColor Yellow
        Stop-Process -Id $OldDownloadPid -ErrorAction Stop
        Wait-Process -Id $OldDownloadPid -ErrorAction SilentlyContinue
    }
}

$RawCount = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir 'data\raw') -Filter '*.parquet' -ErrorAction SilentlyContinue).Count
$QfqCount = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir 'data\qfq') -Filter '*.parquet' -ErrorAction SilentlyContinue).Count
Write-Host "Checkpoint: raw=$RawCount, qfq=$QfqCount." -ForegroundColor Green
Write-Host 'Downloading. Press Ctrl+C to pause; completed files are preserved.' -ForegroundColor Cyan

$CurrentProcess = Start-Process -FilePath $PythonPath -ArgumentList @($RunScript, 'download') -WorkingDirectory $ProjectDir -NoNewWindow -PassThru
$CurrentProcess.Id | Set-Content -LiteralPath $PidFile
$CurrentProcess.WaitForExit()
if ($CurrentProcess.ExitCode -ne 0) {
    throw "Downloader exited with code $($CurrentProcess.ExitCode)."
}
Write-Host 'All download tasks finished.' -ForegroundColor Green
