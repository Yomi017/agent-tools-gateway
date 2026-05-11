$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Root -like "\\*") {
    & "$Root\install-local.ps1"
    $Root = Join-Path (Join-Path $env:LOCALAPPDATA "WinDesktopBridge") "app"
}
Set-Location $Root

& "$Root\install-deps.ps1"
& "$Root\run-server.ps1"
