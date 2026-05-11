$ErrorActionPreference = "Stop"

$StateDir = Join-Path $env:LOCALAPPDATA "WinDesktopBridge"
$PidPath = Join-Path $StateDir "bridge.pid"

$Stopped = $false

if (Test-Path $PidPath) {
    $PidText = (Get-Content $PidPath -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($PidText -match "^\d+$") {
        $Process = Get-Process -Id ([int]$PidText) -ErrorAction SilentlyContinue
        if ($Process) {
            Stop-Process -Id $Process.Id -Force
            $Stopped = $true
        }
    }
    Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
}

$BridgeProcesses = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*windesktop_bridge.py*" }

foreach ($BridgeProcess in $BridgeProcesses) {
    Stop-Process -Id $BridgeProcess.ProcessId -Force -ErrorAction SilentlyContinue
    $Stopped = $true
}

if ($Stopped) {
    Write-Host "WinDesktop bridge stopped."
} else {
    Write-Host "No WinDesktop bridge process was found."
}
