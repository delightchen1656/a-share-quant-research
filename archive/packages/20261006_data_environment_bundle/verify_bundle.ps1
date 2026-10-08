$ErrorActionPreference = 'Stop'
$Bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$Summary = Get-Content (Join-Path $Bundle 'data_summary.json') -Raw | ConvertFrom-Json
foreach ($Item in $Summary) {
    $Path = Join-Path $Bundle $Item.archive
    if (-not (Test-Path -LiteralPath $Path)) { throw "Missing file: $Path" }
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($Actual -ne $Item.sha256) { throw "Hash mismatch: $($Item.archive)" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = [IO.Compression.ZipFile]::OpenRead($Path)
    try { $Count = $Zip.Entries.Count } finally { $Zip.Dispose() }
    if ($Count -ne [int]$Item.files) { throw "File count mismatch: $($Item.archive)" }
    Write-Host "PASS: $($Item.archive) ($Count files)"
}
$Installers = Get-Content (Join-Path $Bundle 'installers\download_sources.json') -Raw | ConvertFrom-Json
foreach ($Item in $Installers) {
    if ($Item.status -ne 'downloaded') { throw "Installer was not downloaded: $($Item.file)" }
    $Path = Join-Path $Bundle (Join-Path 'installers' $Item.file)
    $Actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    if ($Actual -ne $Item.sha256) { throw "Installer hash mismatch: $($Item.file)" }
    Write-Host "PASS: $($Item.file)"
}
Write-Host 'All bundle integrity checks passed.'
