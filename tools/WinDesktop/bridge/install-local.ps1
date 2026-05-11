$ErrorActionPreference = "Stop"

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = Join-Path $env:LOCALAPPDATA "WinDesktopBridge"
$AppDir = Join-Path $StateDir "app"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

$Files = @(
    "install-deps.ps1",
    "install-local.ps1",
    "install-startup-task.ps1",
    "requirements.txt",
    "run-server.ps1",
    "run.ps1",
    "start-background.ps1",
    "stop-background.ps1",
    "uninstall-startup-task.ps1",
    "windesktop_bridge.py"
)

foreach ($File in $Files) {
    $Source = Join-Path $SourceRoot $File
    $Target = Join-Path $AppDir $File
    if (Test-Path $Source) {
        if ((Resolve-Path $Source).Path -ne (Resolve-Path $Target -ErrorAction SilentlyContinue).Path) {
            Copy-Item -Path $Source -Destination $Target -Force
        }
    }
}

Write-Host "WinDesktop bridge app installed to: $AppDir"
