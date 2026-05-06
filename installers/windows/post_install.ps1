<#
.SYNOPSIS
    Runs during install — creates the venv and pip-installs Chika.

.DESCRIPTION
    Inno's [Run] section invokes this with the install dir + wheel
    name. We:

      1. Locate Python 3.11+ on PATH (or via py launcher)
      2. Create ``<install>\venv`` if it doesn't already exist
      3. Upgrade pip in the venv (avoids the "your pip is old" warning)
      4. ``pip install`` the bundled wheel into the venv
      5. Drop a friendly success message into install.log

    On failure we write a clear error message to install.log and
    return a non-zero exit code so Inno surfaces the failure to the
    user instead of silently leaving them with a broken install.

.PARAMETER InstallDir
    Where Chika is installed. Inno passes ``{app}`` for this.

.PARAMETER WheelName
    Filename of the bundled wheel under ``<InstallDir>\wheels\``.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $InstallDir,
    [Parameter(Mandatory)]
    [string] $WheelName
)

$ErrorActionPreference = 'Stop'
$logFile = Join-Path $InstallDir 'install.log'

function Write-Log {
    param([string] $Message, [string] $Level = 'INFO')
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$stamp] [$Level] $Message"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

function Find-Python {
    # Prefer ``py -3.11`` then ``py -3`` then ``python``. The py
    # launcher is the recommended way to find a usable Python on
    # Windows because it handles multiple installs.
    $candidates = @(
        @{ Cmd = 'py'; Args = @('-3.11', '--version') },
        @{ Cmd = 'py'; Args = @('-3.12', '--version') },
        @{ Cmd = 'py'; Args = @('-3.13', '--version') },
        @{ Cmd = 'py'; Args = @('-3', '--version') },
        @{ Cmd = 'python'; Args = @('--version') }
    )
    foreach ($c in $candidates) {
        try {
            $out = & $c.Cmd @($c.Args) 2>&1
            if ($LASTEXITCODE -eq 0 -and $out -match 'Python\s+(\d+)\.(\d+)') {
                $major = [int] $matches[1]
                $minor = [int] $matches[2]
                if (($major -gt 3) -or ($major -eq 3 -and $minor -ge 11)) {
                    Write-Log "Found Python $major.$minor via '$($c.Cmd) $($c.Args -join ' ')'"
                    return @{ Cmd = $c.Cmd; LauncherArgs = ($c.Args | Select-Object -First 1) }
                }
            }
        } catch {
            # Try the next candidate
        }
    }
    return $null
}

try {
    Write-Log "post_install.ps1 starting in $InstallDir"

    $py = Find-Python
    if (-not $py) {
        Write-Log "Python 3.11+ not found on PATH" 'ERROR'
        Write-Log "Opening https://www.python.org/downloads/windows/ in your default browser" 'INFO'
        Write-Log "After installing Python 3.11+, re-run the Chika installer." 'INFO'
        # Best-effort: launch python.org so the user has an obvious
        # next action. ``Start-Process`` is non-blocking so a stuck
        # browser launch won't hang the installer.
        try {
            Start-Process "https://www.python.org/downloads/windows/" -ErrorAction SilentlyContinue
        } catch {
            # Couldn't open the URL — install.log already records the
            # diagnostic; the user will see it via ``chika doctor`` once
            # they install Python and try again.
        }
        # We don't raise here — Inno would otherwise tell the user
        # "install failed" when actually all that's missing is Python.
        # install.log explains the diagnostic clearly.
        exit 1
    }

    $venvDir = Join-Path $InstallDir 'venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    $venvPip = Join-Path $venvDir 'Scripts\pip.exe'

    if (Test-Path $venvPython) {
        Write-Log "Re-using existing venv at $venvDir"
    } else {
        Write-Log "Creating venv at $venvDir"
        if ($py.Cmd -eq 'py') {
            & py $py.LauncherArgs '-m' 'venv' $venvDir
        } else {
            & python -m venv $venvDir
        }
        if ($LASTEXITCODE -ne 0) {
            throw "venv creation failed with exit code $LASTEXITCODE"
        }
    }

    # Upgrade pip first — old pip versions choke on modern wheel
    # metadata in subtle ways.
    Write-Log "Upgrading pip in venv"
    & $venvPython -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Log "pip upgrade failed (exit $LASTEXITCODE) — continuing anyway" 'WARN'
    }

    $wheelPath = Join-Path $InstallDir "wheels\$WheelName"
    if (-not (Test-Path $wheelPath)) {
        throw "Bundled wheel not found at $wheelPath"
    }

    Write-Log "Installing $WheelName into venv"
    # ``--force-reinstall`` so an upgrade-install correctly replaces
    # an older version even when pip thinks "this version is already
    # installed" (file timestamp diffs can mask actual replacements).
    & $venvPip install --upgrade --force-reinstall $wheelPath --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "pip install of $WheelName failed with exit code $LASTEXITCODE"
    }

    # Sanity check: the venv should now expose chika.exe.
    $venvChika = Join-Path $venvDir 'Scripts\chika.exe'
    if (-not (Test-Path $venvChika)) {
        throw "After install, $venvChika does not exist — something went wrong"
    }

    Write-Log "Install complete — chika.exe is at $venvChika" 'OK'

    # Extension detection — let the user know if their browser already
    # has the extension loaded. The installer's success page just
    # surfaces "extension installed" copy; we write the detection
    # result to a file the post-install dialog can read.
    try {
        $detectScript = @"
from chika._cli.extension_detect import detect_extension
r = detect_extension()
print(r.confidence, '|', '; '.join(f'{n}={d}' for n, d in r.signals[:3]))
"@
        $detectOut = & $venvPython -c $detectScript 2>$null
        if ($LASTEXITCODE -eq 0 -and $detectOut) {
            Set-Content -Path "$InstallDir\extension_detection.txt" -Value $detectOut -Encoding UTF8
            Write-Log "Extension detection: $detectOut" 'INFO'
        }
    } catch {
        # Detection is purely informational — install still succeeded.
        Write-Log "Extension detection skipped: $_" 'WARN'
    }

    exit 0
}
catch {
    Write-Log "FATAL: $_" 'ERROR'
    Write-Log "See $logFile for details" 'ERROR'
    exit 1
}
