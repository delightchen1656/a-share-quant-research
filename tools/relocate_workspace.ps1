$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$audit = Join-Path $repo 'project_memory\holdout_restricted\layout_20261031'
if (-not (Test-Path -LiteralPath (Join-Path $audit 'inventory.json'))) { throw 'Pre-migration inventory missing' }
if (Test-Path -LiteralPath (Join-Path $audit 'moves_completed.json')) { throw 'Relocation already executed; inspect its audit before any further move' }
$active = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'daily_market_update\.py|backfill_hushen_history\.py|auto_update_gold\.py' }
if ($active) { throw 'Market updater still running' }
$task = Get-ScheduledTask -TaskName 'Hushen2_Orbit_1830'
if ($task.State -eq 'Running') { throw 'Orbit task still running' }
Export-ScheduledTask -TaskName $task.TaskName | Set-Content -LiteralPath (Join-Path $audit 'orbit_task_before.xml') -Encoding utf8
Disable-ScheduledTask -TaskName $task.TaskName | Out-Null
# Only stop the verified read-only viewer, after saving its API response snapshot.
$viewers = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -like '*quant\K线看盘软件\app.py*' }
foreach ($viewer in $viewers) { Stop-Process -Id $viewer.ProcessId -ErrorAction SilentlyContinue }
$moves = Get-Content -LiteralPath (Join-Path $audit 'moves.json') -Raw | ConvertFrom-Json
$done = @()
foreach ($move in $moves) {
    $source = [IO.Path]::GetFullPath((Join-Path $repo $move.old))
    $target = [IO.Path]::GetFullPath((Join-Path $repo $move.new))
    if (-not $source.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase) -or -not $target.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Target outside repository' }
    if (-not (Test-Path -LiteralPath $source)) { throw "Source missing: $source" }
    if (Test-Path -LiteralPath $target) { throw "Destination already exists: $target" }
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
    Move-Item -LiteralPath $source -Destination $target
    $done += $move
    ConvertTo-Json -InputObject $done -Depth 5 | Set-Content -LiteralPath (Join-Path $audit 'moves_completed.json') -Encoding utf8
    Write-Output ('Moved: ' + $move.old + ' -> ' + $move.new)
}
Write-Output 'Physical relocation complete; scheduled task remains disabled until validation.'
