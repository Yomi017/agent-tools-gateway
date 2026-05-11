$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = Join-Path $env:LOCALAPPDATA "WinDesktopBridge"
$AppDir = Join-Path $StateDir "app"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$StartupLog = Join-Path $StateDir "startup.log"

function Write-StartupLog {
    param([string]$Message)
    "[$(Get-Date -Format o)] $Message" | Add-Content -Path $StartupLog
}

Write-StartupLog "start-background entered root=$Root app=$AppDir"

if ($Root -ne $AppDir) {
    Write-StartupLog "installing local app from shared folder"
    & "$Root\install-local.ps1"
    $Root = $AppDir
}

Set-Location $Root
$PidPath = Join-Path $StateDir "bridge.pid"

function Test-BridgeHealth {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:18787/health?compact=true" -TimeoutSec 2
        return ($response.ok -eq $true)
    } catch {
        return $false
    }
}

if (Test-BridgeHealth) {
    Write-Host "WinDesktop bridge is already running."
    Write-StartupLog "bridge already healthy"
    exit 0
}

Write-StartupLog "stopping stale windesktop_bridge.py processes"
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*windesktop_bridge.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-StartupLog "installing dependencies"
& "$Root\install-deps.ps1"

Write-StartupLog "starting hidden run-server.ps1"
$Process = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden",
        "-File", "`"$Root\run-server.ps1`""
    ) `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -PassThru

$Process.Id | Set-Content -Path $PidPath -Encoding ascii
Write-StartupLog "started process pid=$($Process.Id)"
Start-Sleep -Seconds 3

foreach ($Attempt in 1..12) {
    if (Test-BridgeHealth) {
        Write-Host "WinDesktop bridge started in background. PID: $($Process.Id)"
        Write-Host "App: $Root"
        Write-Host "Log: $StateDir\bridge.log"
        Write-StartupLog "bridge healthy attempt=$Attempt"
        exit 0
    }
    Write-StartupLog "health check failed attempt=$Attempt"
    Start-Sleep -Seconds 1
}

Write-StartupLog "bridge health did not pass"
throw "WinDesktop bridge was started but health check did not pass. Check $StateDir\bridge.log"
