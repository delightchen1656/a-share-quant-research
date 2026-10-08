param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$Bundle = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Expand-Archive -LiteralPath (Join-Path $Bundle '01_hushen_data.zip') -DestinationPath $Target -Force
Expand-Archive -LiteralPath (Join-Path $Bundle '02_kechuang_data.zip') -DestinationPath $Target -Force
Write-Host "Market data restored to $Target"
Write-Host 'The provenance/backup archive is not extracted by default.'
