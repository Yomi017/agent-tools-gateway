# WinDesktop Bridge

Local Windows VM desktop bridge for the Hermes desktop-agent sandbox.

This bridge exposes read-only inspection endpoints plus explicit input
primitives for operator-approved desktop control:

- `GET /health`
- `GET /screenshot`
- `GET /windows`
- `POST /focus-window`
- `POST /click`
- `POST /type`
- `POST /hotkey`

It is intended to run inside the dedicated Windows 11 VMware guest. The
ToolHub `windesktop_*` tools call this bridge over the host-only VM network.
Screenshots are written to the VMware shared folder instead of being streamed
over HTTP.

`/focus-window`, `/click`, `/type`, and `/hotkey` change the interactive desktop
state. Use them only after the operator confirms the exact target and action.
The preferred typing mode is clipboard paste, which is more reliable for Chinese
and long text than synthetic per-key input.

## Install and Run in the VM

Copy the `bridge` directory into the VM, for example through the shared
`Z:` drive, then run PowerShell in that directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\run.ps1
```

For normal use, run it in the background instead:

```powershell
.\start-background.ps1
```

To stop the background bridge:

```powershell
.\stop-background.ps1
```

To start it automatically after this Windows user logs in:

```powershell
.\install-startup-task.ps1
```

The startup task deliberately runs at user logon, not as a Windows service,
because desktop capture needs the interactive user session. To remove it:

```powershell
.\uninstall-startup-task.ps1
```

The default listener is:

```text
http://0.0.0.0:18787
```

The default screenshot output directory is:

```text
\\vmware-host\Shared Folders\HermesVMShare\WinDesktopOutput
```

If Windows Firewall prompts, allow access on private networks only.

Background logs are written to:

```text
%LOCALAPPDATA%\WinDesktopBridge\bridge.log
```

## Optional Token

Set `WINDESKTOP_TOKEN` before running the bridge to require a bearer token:

```powershell
$env:WINDESKTOP_TOKEN = "change-me"
.\run.ps1
```
