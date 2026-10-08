$ErrorActionPreference = 'Stop'
$Bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = Join-Path $Bundle 'local_project'

Write-Host '[1/7] Verifying transfer integrity...'
& (Join-Path $Bundle 'verify_bundle.ps1')

Write-Host '[2/7] Restoring market data...'
$RequiredData = Join-Path $Project 'sh_sz_market_research\data_pipeline\data\raw\SH\600000.SH.parquet'
if (-not (Test-Path -LiteralPath $RequiredData)) {
    & (Join-Path $Bundle 'restore_data.ps1') -Destination $Project
} else {
    Write-Host 'Market data already restored; skipping extraction.'
}

Write-Host '[3/7] Locating Python 3.10...'
function Find-Python310 {
    $Candidates = @(
        (Join-Path $env:LocalAppData 'Programs\Python\Python310\python.exe'),
        'C:\Program Files\Python310\python.exe'
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate) {
            $Version = & $Candidate -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null
            if ($Version -eq '3.10.11') { return $Candidate }
        }
    }
    try {
        $Found = & py -3.10 -c "import sys;print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $Found)) {
            $Version = & $Found -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null
            if ($Version -eq '3.10.11') { return $Found }
        }
    } catch {}
    return $null
}
$Python = Find-Python310
if (-not $Python) {
    Write-Host 'Installing bundled Python 3.10.11 for the current user...'
    $Installer = Join-Path $Bundle 'installers\python-3.10.11-amd64.exe'
    $Process = Start-Process -FilePath $Installer -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0',
        'Include_launcher=1', 'InstallLauncherAllUsers=0'
    ) -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw "Python installer exited with code $($Process.ExitCode)" }
    $Python = Find-Python310
}
if (-not $Python) { throw 'Python 3.10 could not be found after installation.' }
Write-Host "Python: $Python"

Write-Host '[4/7] Creating the isolated environment...'
$VenvPython = Join-Path $Project 'quant_env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $Python -m venv (Join-Path $Project 'quant_env')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the virtual environment.' }
}
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Failed to upgrade pip. Check internet access.' }
& $VenvPython -m pip install -r (Join-Path $Bundle 'environment\requirements.core.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install Python packages. Check internet access.' }

Write-Host '[5/7] Running rule tests and the sample backtest...'
& $VenvPython -m unittest discover (Join-Path $Bundle 'basic_backtest_example') -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Example tests failed.' }
& $VenvPython (Join-Path $Bundle 'basic_backtest_example\local_backtest.py') `
    --project-root $Project --output (Join-Path $Bundle 'basic_backtest_example\output')
if ($LASTEXITCODE -ne 0) { throw 'Sample backtest failed.' }

Write-Host '[6/7] Building the standalone SuperMind source...'
& $VenvPython (Join-Path $Bundle 'basic_backtest_example\build_supermind.py')
if ($LASTEXITCODE -ne 0) { throw 'SuperMind source build failed.' }
$Ready = Get-ChildItem -LiteralPath (Join-Path $Bundle 'basic_backtest_example') -File -Filter '*SuperMind*.py' |
    Where-Object { $_.Name -notlike '*template*' -and $_.Name -notlike '*test*' } |
    Select-Object -First 1
if (-not $Ready) { throw 'Generated SuperMind strategy was not found.' }
Get-Content -LiteralPath $Ready.FullName -Raw | Set-Clipboard
Write-Host 'SuperMind source copied to the clipboard.'

Write-Host '[7/7] Starting the bundled SuperMind installer...'
$Marker = Join-Path $Bundle 'local_project\.supermind_installer_completed'
if (-not (Test-Path -LiteralPath $Marker)) {
    $SuperMind = Join-Path $Bundle 'installers\SuperMind_TYB_v8.18.1.9791.exe'
    $Process = Start-Process -FilePath $SuperMind -Wait -PassThru
    if ($Process.ExitCode -ne 0) { throw "SuperMind installer exited with code $($Process.ExitCode)" }
    Set-Content -LiteralPath $Marker -Value (Get-Date -Format o) -Encoding Ascii
} else {
    Write-Host 'SuperMind installer was already completed by this setup.'
}

Write-Host ''
Write-Host 'READY.'
Write-Host "Local project: $Project"
Write-Host "Strategy files: $Bundle\basic_backtest_example"
