$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$StateDir = Join-Path $env:LOCALAPPDATA "WinDesktopBridge"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
$LogPath = Join-Path $StateDir "bridge.log"

if (-not $env:WINDESKTOP_HOST) {
    $env:WINDESKTOP_HOST = "0.0.0.0"
}
if (-not $env:WINDESKTOP_PORT) {
    $env:WINDESKTOP_PORT = "18787"
}
if (-not $env:WINDESKTOP_OUTPUT_DIR) {
    $env:WINDESKTOP_OUTPUT_DIR = "\\vmware-host\Shared Folders\HermesVMShare\WinDesktopOutput"
}

"[$(Get-Date -Format o)] starting windesktop bridge" | Add-Content -Path $LogPath
$PythonPath = Join-Path $Root ".venv\Scripts\python.exe"
"[$(Get-Date -Format o)] root=$Root" | Add-Content -Path $LogPath
"[$(Get-Date -Format o)] python=$PythonPath exists=$(Test-Path $PythonPath)" | Add-Content -Path $LogPath

try {
    & $PythonPath "-c" "import fastapi, uvicorn, PIL, win32gui; print('import check ok')" *>> $LogPath
    "[$(Get-Date -Format o)] import-check exit=$LASTEXITCODE" | Add-Content -Path $LogPath
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    "[$(Get-Date -Format o)] launching bridge python via cmd redirection" | Add-Content -Path $LogPath
    $Command = "`"$PythonPath`" `"$Root\windesktop_bridge.py`" >> `"$LogPath`" 2>&1"
    & "$env:ComSpec" /d /c $Command
    $BridgeExitCode = $LASTEXITCODE
    "[$(Get-Date -Format o)] bridge python exit=$BridgeExitCode" | Add-Content -Path $LogPath
    exit $BridgeExitCode
} catch {
    "[$(Get-Date -Format o)] run-server exception:" | Add-Content -Path $LogPath
    ($_ | Out-String) | Add-Content -Path $LogPath
    throw
}
