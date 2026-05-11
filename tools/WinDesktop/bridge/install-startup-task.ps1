$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "WinDesktopBridge"

& "$Root\install-local.ps1"

$StateDir = Join-Path $env:LOCALAPPDATA "WinDesktopBridge"
$AppDir = Join-Path $StateDir "app"
& "$AppDir\install-deps.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$AppDir\start-background.ps1`"" `
    -WorkingDirectory $AppDir

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Start the Hermes WinDesktop bridge when the VM user logs in." `
    -Force | Out-Null

Write-Host "Installed and started scheduled task: $TaskName"
Write-Host "The bridge starts after this Windows user logs in. It is not a Session 0 service."

Write-Host "Starting bridge immediately from local app directory..."
& "$AppDir\start-background.ps1"
