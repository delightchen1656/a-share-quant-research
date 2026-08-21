$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DataDir = Join-Path $ProjectDir 'data'
$UniversePath = Join-Path $DataDir 'metadata\universe.csv'
$ClassifiedDir = Join-Path $DataDir 'classified'

if (-not (Test-Path -LiteralPath $UniversePath -PathType Leaf)) {
    throw "Universe file not found: $UniversePath"
}

$Universe = @(Import-Csv -LiteralPath $UniversePath)
if ($Universe.Count -eq 0) {
    throw 'Universe is empty.'
}

$Manifest = [System.Collections.Generic.List[object]]::new()
$Missing = [System.Collections.Generic.List[string]]::new()
$Linked = 0
$Existing = 0

foreach ($Row in $Universe) {
    $Parts = $Row.symbol.Split('.')
    if ($Parts.Count -ne 2) {
        $Missing.Add("Invalid symbol: $($Row.symbol)")
        continue
    }
    $Code = $Parts[0]
    $Exchange = $Parts[1]
    if ($Exchange -eq 'SH' -and ($Code.StartsWith('688') -or $Code.StartsWith('689'))) {
        $Board = 'star'
    } elseif ($Exchange -eq 'SZ' -and ($Code.StartsWith('300') -or $Code.StartsWith('301'))) {
        $Board = 'chinext'
    } elseif ($Exchange -eq 'SH' -or $Exchange -eq 'SZ') {
        $Board = 'main'
    } else {
        $Board = 'other'
    }

    $Paths = @{}
    $SymbolOk = $true
    foreach ($Kind in @('raw', 'qfq')) {
        $Source = Join-Path $DataDir "$Kind\$($Row.symbol).parquet"
        $Folder = Join-Path $ClassifiedDir "$Exchange\$Board\$Kind"
        $Target = Join-Path $Folder "$($Row.symbol).parquet"
        if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
            $Missing.Add($Source)
            $SymbolOk = $false
            continue
        }
        New-Item -ItemType Directory -Path $Folder -Force | Out-Null
        if (Test-Path -LiteralPath $Target) {
            $Existing++
        } else {
            New-Item -ItemType HardLink -Path $Target -Target $Source | Out-Null
            $Linked++
        }
        $Paths[$Kind] = $Target.Substring($ProjectDir.Length + 1)
    }
    if ($SymbolOk) {
        $Manifest.Add([pscustomobject]@{
            symbol = $Row.symbol
            name = $Row.code_name
            exchange = $Exchange
            board = $Board
            ipo_date = $Row.ipoDate
            raw_path = $Paths['raw']
            qfq_path = $Paths['qfq']
        })
    }
}

$MetadataDir = Join-Path $DataDir 'metadata'
$Manifest | Sort-Object exchange, board, symbol | Export-Csv -LiteralPath (Join-Path $MetadataDir 'classified_manifest.csv') -NoTypeInformation -Encoding UTF8
$Manifest | Group-Object exchange, board | ForEach-Object {
    [pscustomobject]@{ category = $_.Name; stocks = $_.Count }
} | Sort-Object category | Export-Csv -LiteralPath (Join-Path $MetadataDir 'classified_summary.csv') -NoTypeInformation -Encoding UTF8
$Missing | Set-Content -LiteralPath (Join-Path $MetadataDir 'classified_missing.txt') -Encoding UTF8

Write-Host "Classified stocks: $($Manifest.Count)"
Write-Host "Hard links created: $Linked; already present: $Existing; missing paths: $($Missing.Count)"
$Manifest | Group-Object exchange, board | Sort-Object Name | Format-Table Name, Count -AutoSize
if ($Missing.Count -gt 0) { exit 2 }
