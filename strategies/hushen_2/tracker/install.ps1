$ErrorActionPreference = 'Stop'
$trackerDir = $PSScriptRoot
$repoDir = (Resolve-Path -LiteralPath (Join-Path $trackerDir '..\..\..')).Path
$pythonWindowless = Join-Path $repoDir 'quant_env\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'quant_env Python runtime missing' }
$shellObject = New-Object -ComObject WScript.Shell
$desktopDir = [Environment]::GetFolderPath('Desktop')
$shortcut = $shellObject.CreateShortcut((Join-Path $desktopDir '沪深2 星轨.lnk'))
$shortcut.TargetPath = $pythonWindowless
$shortcut.Arguments = '-B "' + (Join-Path $trackerDir 'launch.pyw') + '"'
$shortcut.WorkingDirectory = $trackerDir
$shortcut.Description = '沪深2 · 晚间交易工作台'
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,17"
$shortcut.Save()
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('-B "' + (Join-Path $trackerDir 'app.py') + '" --update --no-open') -WorkingDirectory $trackerDir
$trigger = New-ScheduledTaskTrigger -Daily -At '18:30'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'Hushen2_Orbit_1830' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description '沪深2本地晚间数据更新，不连接券商、不自动下单' -Force | Out-Null
Get-ScheduledTask -TaskName 'Hushen2_Orbit_1830' | Select-Object TaskName,State
Write-Output (Join-Path $desktopDir '沪深2 星轨.lnk')
