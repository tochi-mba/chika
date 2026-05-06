<#
.SYNOPSIS
    Runs during uninstall — clean up things Inno itself can't.

.DESCRIPTION
    Inno's auto-generated uninstaller wipes the install dir, PATH
    entry, Start Menu group, and Add/Remove Programs entry. This
    script handles what's left:

      1. Remove the install dir from the user's PATH (Inno only knows
         how to delete registry values it created itself; we appended
         to an existing Path value during install, so we have to
         strip our entry by hand).

      2. Optionally remove user data at ``%USERPROFILE%\.chika\``.
         We default to *keeping* it — a "clean" uninstall removes the
         app, not the user's settings, profiles, chat history, etc.
         If you want a full nuke, delete that folder manually after
         uninstall.

    install.log + uninstall.log capture the diagnostics so even a
    silent uninstall is debuggable after the fact.

.PARAMETER InstallDir
    The install dir Inno is about to remove. Inno passes ``{app}``.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $InstallDir
)

$ErrorActionPreference = 'Continue'  # uninstall must always finish

$logFile = Join-Path $InstallDir 'uninstall.log'
function Write-Log {
    param([string] $Message, [string] $Level = 'INFO')
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logFile -Value "[$stamp] [$Level] $Message" -Encoding UTF8
}

Write-Log "pre_uninstall.ps1 starting"

# ── Strip the install dir from the user's PATH ────────────────────────

try {
    $envKey = 'HKCU:\Environment'
    $current = (Get-ItemProperty -Path $envKey -Name Path -ErrorAction SilentlyContinue).Path
    if ($current) {
        # Filter out our entry. Match exact (case-insensitive) — don't
        # touch entries that just happen to contain the install dir's
        # name as a substring.
        $parts = $current -split ';' | Where-Object {
            $_ -ne '' -and $_.TrimEnd('\') -ne $InstallDir.TrimEnd('\')
        }
        $newPath = ($parts -join ';').TrimEnd(';')
        if ($newPath -ne $current) {
            Set-ItemProperty -Path $envKey -Name Path -Value $newPath -Type ExpandString
            Write-Log "Removed $InstallDir from user PATH"
            # Tell Explorer/cmd to reload env on next session — broadcast
            # WM_SETTINGCHANGE. New shells get the new PATH, current
            # shells stay on the cached one (fine for an uninstall).
            try {
                $sig = '[DllImport("user32.dll", SetLastError=true, CharSet=CharSet.Auto)] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);'
                $type = Add-Type -MemberDefinition $sig -Name 'NativeMethods' -Namespace 'ChikaUninstall' -PassThru -ErrorAction SilentlyContinue
                if ($type) {
                    $HWND_BROADCAST = [IntPtr]0xffff
                    $WM_SETTINGCHANGE = 0x1A
                    $result = [UIntPtr]::Zero
                    $type::SendMessageTimeout($HWND_BROADCAST, $WM_SETTINGCHANGE, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result) | Out-Null
                }
            } catch {
                Write-Log "PATH broadcast failed (cosmetic): $_" 'WARN'
            }
        } else {
            Write-Log "Install dir was not on PATH; nothing to strip"
        }
    } else {
        Write-Log "User PATH is empty or unreadable; nothing to strip"
    }
} catch {
    Write-Log "PATH cleanup failed: $_" 'WARN'
}

# ── User data: leave it alone unless explicitly asked ─────────────────
#
# Future: read a flag from a checkbox on the uninstaller wizard —
# Inno's [Code] section can drive an InitializeUninstall callback
# that prompts the user "Also remove all Chika settings, profiles,
# and chat history?" and then writes a marker file we read here. For
# now, default behaviour is the safer one.

$userDataDir = Join-Path $env:USERPROFILE '.chika'
if (Test-Path $userDataDir) {
    Write-Log "User data dir preserved: $userDataDir"
    Write-Log "  (delete manually if you want a clean removal)"
}

# ── Browser-extension reminder ────────────────────────────────────────
#
# Inno Setup can only remove files the installer itself placed. The
# Chrome extension lives in the user's browser profile and was loaded
# via "Load unpacked" — we never touched the browser, so we can't
# remove it. But we CAN detect that it's still there and remind the
# user to disable / remove it manually.
#
# Detection runs against the venv we're about to delete, so we run it
# *before* removing anything.

$venvPython = Join-Path $InstallDir 'venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    try {
        $detectOut = & $venvPython -c "from chika._cli.extension_detect import detect_extension; r = detect_extension(); print(r.confidence)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $detectOut) {
            $confidence = $detectOut.Trim()
            Write-Log "Extension detection: $confidence"
            if ($confidence -in @('confirmed_active', 'present_in_chrome_profile')) {
                # Write a marker the installer's success page can read
                # (or the user can find later in the install dir).
                $reminder = @"
The Chika browser extension was detected as still loaded in your
browser. The Windows uninstaller cannot reach inside Chrome's profile
to remove it.

To finish the uninstall:
  1. Open chrome://extensions/
  2. Find "Chika Browser Agent"
  3. Click Remove
"@
                Set-Content -Path "$env:USERPROFILE\.chika\uninstall_reminder.txt" -Value $reminder -Encoding UTF8
                Write-Log "Wrote extension-removal reminder to ~/.chika/uninstall_reminder.txt"
            }
        }
    } catch {
        Write-Log "Extension detection during uninstall skipped: $_" 'WARN'
    }
}

Write-Log "pre_uninstall.ps1 done"
exit 0
