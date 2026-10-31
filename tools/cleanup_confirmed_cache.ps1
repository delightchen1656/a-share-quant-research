param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$audit = Join-Path $repo 'project_memory\holdout_restricted\module_independence_20261031'
$plan = Get-Content -LiteralPath (Join-Path $audit 'approved_cache_plan.json') -Raw | ConvertFrom-Json
$bytecode = [IO.Path]::GetFullPath((Join-Path $repo 'project_memory\holdout_restricted\layout_20261031\bytecode'))
$tempRoot = (Resolve-Path -LiteralPath $env:TEMP).Path
$tempNames = @('hushen2_buy_workflow_qa_hcrzrhup','hushen2_buy_workflow_qa_kiukz7gf',
  'hushen2_manual_exit_ui_4m9mr6y1','hushen2_tracking_qa_rak3sa3n',
  'hushen2_upgrade_rehearsal_yrbbiw0q','quant-recover-3843ec79f3f842568cce1d961b84f363')
$allowed = @($bytecode) + @($tempNames | ForEach-Object { Join-Path $tempRoot $_ })
function Assert-Target([string]$target) {
  $full = [IO.Path]::GetFullPath($target)
  $matched = @($allowed | Where-Object { $full -eq $_ -or $full.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) })
  if ($matched.Count -ne 1) { throw "Outside explicit cache allowlist: $full" }
  $cursor = $full
  while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
      $item = Get-Item -LiteralPath $cursor -Force
      if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $cursor" }
    }
    $cursor = [IO.Path]::GetDirectoryName($cursor)
  }
  return $full
}
$processes = Get-CimInstance Win32_Process
foreach ($name in $tempNames) {
  if (@($processes | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($name) }).Count) {
    throw "Temporary directory referenced by live process: $name"
  }
}
if (@($processes | Where-Object { $_.CommandLine -match 'qa_hushen2_buy_workflow.py|preview_manual_exit.py|preview_tracking.py' }).Count) {
  throw 'QA producer process is running'
}
# Validate every exact file before the first deletion. No recursive delete.
foreach ($entry in $plan.files) {
  $target = Assert-Target $entry.path
  if (!(Test-Path -LiteralPath $target -PathType Leaf)) { throw "Missing candidate: $target" }
  if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
    throw "Candidate changed: $target"
  }
}
foreach ($dir in $plan.empty_directories) { $null = Assert-Target $dir }
if (!$Apply) { Write-Output "Validated $($plan.file_count) files, $($plan.bytes) bytes; use -Apply for exact-file deletion."; exit 0 }
$deleted = [System.Collections.Generic.List[string]]::new()
$removedDirs = [System.Collections.Generic.List[string]]::new()
try {
  foreach ($entry in $plan.files) {
    $target = Assert-Target $entry.path
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "Candidate changed: $target" }
    Remove-Item -LiteralPath $target -Force
    $deleted.Add($target)
  }
  foreach ($dir in ($plan.empty_directories | Sort-Object Length -Descending)) {
    $target = Assert-Target $dir
    if ((Test-Path -LiteralPath $target) -and @(Get-ChildItem -LiteralPath $target -Force).Count -eq 0) {
      Remove-Item -LiteralPath $target
      $removedDirs.Add($target)
    }
  }
} finally {
  @{deleted_files=$deleted.ToArray(); removed_empty_directories=$removedDirs.ToArray(); planned_bytes=$plan.bytes; completed=($deleted.Count -eq $plan.file_count)} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $audit 'cache_deletion_result.json') -Encoding utf8
}
Write-Output "Physically deleted $($deleted.Count) files and $($removedDirs.Count) empty directories."
