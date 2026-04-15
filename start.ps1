<#
.SYNOPSIS
    Chika v2 smart launcher.

.DESCRIPTION
    First run  (no desktop shortcut exists):
        Creates the shortcut, then starts BOTH backend AND frontend in separate windows.

    Subsequent runs (shortcut already on desktop):
        Starts the BACKEND only. Frontend is untouched.

    Flags:
        -All           Force start both backend + frontend regardless of shortcut state.
        -FrontendOnly  Start only the frontend (handy if backend is already up).
        -Kill          Kill whatever owns the ports first, then start fresh.

.EXAMPLE
    .\start.ps1              # smart: first-run = both, repeat = backend only
    .\start.ps1 -All         # always start both
    .\start.ps1 -FrontendOnly
    .\start.ps1 -Kill -All   # nuke existing processes, restart everything
#>

param(
    [switch]$All,
    [switch]$FrontendOnly,
    [switch]$Kill
)

# ── Config ──────────────────────────────────────────────────────────────────
$ROOT          = $PSScriptRoot
$BACKEND_PORT  = 8000
$FRONTEND_PORT = 5173
$SHORTCUT_PATH = Join-Path $env:USERPROFILE "Desktop\Chika.lnk"

$BACKEND_SCRIPT  = Join-Path $ROOT "_run_backend.ps1"
$FRONTEND_SCRIPT = Join-Path $ROOT "_run_frontend.ps1"

# ── Helpers ─────────────────────────────────────────────────────────────────

function Write-Step { param([string]$m) Write-Host ""; Write-Host "  >> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "  [!!] $m" -ForegroundColor Yellow }

function Test-PortInUse {
    param([int]$Port)
    return ($null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue))
}

function Stop-PortProcess {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) { return }
    foreach ($c in $conns) {
        $p = $c.OwningProcess
        if ($p -and $p -ne 0) {
            $name = (Get-Process -Id $p -ErrorAction SilentlyContinue).ProcessName
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            Write-Ok "Killed '$name' (PID $p) on port $Port"
        }
    }
    Start-Sleep -Milliseconds 600
}

function New-DesktopShortcut {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk   = $shell.CreateShortcut($SHORTCUT_PATH)
        $lnk.TargetPath       = "powershell.exe"
        $lnk.Arguments        = '-ExecutionPolicy Bypass -File "' + $ROOT + '\start.ps1"'
        $lnk.WorkingDirectory = $ROOT
        $lnk.Description      = "Start Chika v2"
        $lnk.IconLocation     = "powershell.exe,0"
        $lnk.Save()
        Write-Ok "Desktop shortcut created -> $SHORTCUT_PATH"
    }
    catch {
        Write-Warn "Could not create shortcut: $_"
    }
}

function Repair-ShortcutIfStale {
    # If a shortcut already exists but no longer points here, rebuild it
    if (-not (Test-Path $SHORTCUT_PATH)) { return }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk   = $shell.CreateShortcut($SHORTCUT_PATH)
        if ($lnk.Arguments -notlike "*start.ps1*") {
            Write-Warn "Shortcut target is stale -- rebuilding..."
            New-DesktopShortcut
        }
    }
    catch {}
}

function Start-Backend {
    if (Test-PortInUse $BACKEND_PORT) {
        if ($Kill) {
            Write-Step "Killing process on port $BACKEND_PORT..."
            Stop-PortProcess $BACKEND_PORT
        }
        else {
            Write-Warn "Port $BACKEND_PORT already in use -- backend may be running. Use -Kill to force restart."
            return
        }
    }
    Write-Step "Launching backend (port $BACKEND_PORT)..."
    Start-Process powershell -ArgumentList @("-ExecutionPolicy", "Bypass", "-NoExit", "-File", $BACKEND_SCRIPT) `
        -WorkingDirectory $ROOT
    Write-Ok "Backend window open -> http://localhost:$BACKEND_PORT"
}

function Start-Frontend {
    if (Test-PortInUse $FRONTEND_PORT) {
        if ($Kill) {
            Write-Step "Killing process on port $FRONTEND_PORT..."
            Stop-PortProcess $FRONTEND_PORT
        }
        else {
            Write-Warn "Port $FRONTEND_PORT already in use -- frontend may be running. Use -Kill to force restart."
            return
        }
    }
    Write-Step "Launching frontend (port $FRONTEND_PORT)..."
    Start-Process powershell -ArgumentList @("-ExecutionPolicy", "Bypass", "-NoExit", "-File", $FRONTEND_SCRIPT) `
        -WorkingDirectory $ROOT
    Write-Ok "Frontend window open -> http://localhost:$FRONTEND_PORT"
}

# ── Banner ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ================================" -ForegroundColor DarkCyan
Write-Host "      Chika v2  --  Launcher      " -ForegroundColor Cyan
Write-Host "  ================================" -ForegroundColor DarkCyan

# ── Main logic ───────────────────────────────────────────────────────────────

$shortcutExists = Test-Path $SHORTCUT_PATH
Repair-ShortcutIfStale

if ($FrontendOnly) {
    # ── frontend only ─────────────────────────────────────────────────────────
    Write-Host "  Mode: frontend only" -ForegroundColor Gray
    Start-Frontend

} elseif (-not $shortcutExists) {
    # ── first run: create shortcut + start everything ─────────────────────────
    Write-Host "  Mode: FIRST RUN -- creating shortcut + starting full stack" -ForegroundColor Gray
    New-DesktopShortcut
    Start-Backend
    Start-Frontend
    Write-Host ""
    Write-Host "  Backend  -> http://localhost:$BACKEND_PORT" -ForegroundColor White
    Write-Host "  Frontend -> http://localhost:$FRONTEND_PORT" -ForegroundColor White

} elseif ($All) {
    # ── forced full start ─────────────────────────────────────────────────────
    Write-Host "  Mode: -All flag -- starting full stack" -ForegroundColor Gray
    Start-Backend
    Start-Frontend
    Write-Host ""
    Write-Host "  Backend  -> http://localhost:$BACKEND_PORT" -ForegroundColor White
    Write-Host "  Frontend -> http://localhost:$FRONTEND_PORT" -ForegroundColor White

} else {
    # ── shortcut already exists: backend only ────────────────────────────────
    Write-Host "  Mode: shortcut exists -- backend only  (use -All to also start frontend)" -ForegroundColor Gray
    Start-Backend
    Write-Host ""
    Write-Host "  Backend  -> http://localhost:$BACKEND_PORT" -ForegroundColor White
    Write-Host "  Frontend -> http://localhost:$FRONTEND_PORT  (not started)" -ForegroundColor DarkGray
}

Write-Host ""
