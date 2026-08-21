$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $ProjectDir 'data\logs\download.pid'
$RawCount = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir 'data\raw') -Filter '*.parquet' -ErrorAction SilentlyContinue).Count
$QfqCount = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir 'data\qfq') -Filter '*.parquet' -ErrorAction SilentlyContinue).Count
$DownloadPid = if (Test-Path -LiteralPath $PidFile) { [int](Get-Content -LiteralPath $PidFile) } else { 0 }
$Running = if ($DownloadPid -gt 0) { $null -ne (Get-Process -Id $DownloadPid -ErrorAction SilentlyContinue) } else { $false }
Write-Output "running=$Running pid=$DownloadPid raw=$RawCount qfq=$QfqCount"
if (Test-Path -LiteralPath (Join-Path $ProjectDir 'data\logs\download_stdout.log')) {
    Get-Content -LiteralPath (Join-Path $ProjectDir 'data\logs\download_stdout.log') -Tail 10
}
