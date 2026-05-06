<#
.SYNOPSIS
    Build the Chika Windows installer.

.DESCRIPTION
    Orchestrates the installer build:

      1. Reads version from pyproject.toml so the installer version
         stays in lock-step with the package version.
      2. Builds a wheel with ``python -m build --wheel``.
      3. Stages the source tree (excluding tests, .git, node_modules,
         __pycache__, etc.) into a clean build dir.
      4. Generates ``install_marker.json`` so the installed copy is
         recognised as ``windows_installer`` by ``chika update``.
      5. Invokes Inno Setup's ISCC.exe with the right ``#define``s.
      6. Outputs ``installers\dist\chika-setup-X.Y.Z.exe``.

.PARAMETER Version
    Override the version detected from pyproject.toml. Useful for
    testing pre-release builds.

.PARAMETER ISCC
    Path to ``ISCC.exe`` (the Inno Setup compiler). Defaults to the
    standard install location. CI sets this via env when running on
    the GitHub Actions runner.

.PARAMETER SkipWheel
    Skip building a fresh wheel (use the existing dist/ wheel). Useful
    in CI where the wheel is built in a separate step for caching.

.EXAMPLE
    .\installers\windows\build_installer.ps1

.EXAMPLE
    .\installers\windows\build_installer.ps1 -Version 2.0.5 -SkipWheel
#>
[CmdletBinding()]
param(
    [string] $Version = '',
    [string] $ISCC = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    [switch] $SkipWheel
)

$ErrorActionPreference = 'Stop'

# Anchor every path off the repo root so this script works from any cwd.
$RepoRoot      = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$InstallerDir  = Join-Path $RepoRoot 'installers\windows'
$BuildDir      = Join-Path $RepoRoot 'build\installer'
$DistDir       = Join-Path $RepoRoot 'installers\dist'
$WheelDir      = Join-Path $RepoRoot 'dist'

function Read-VersionFromPyproject {
    $pyproject = Join-Path $RepoRoot 'pyproject.toml'
    $line = Get-Content $pyproject |
        Where-Object { $_ -match '^\s*version\s*=\s*"([^"]+)"' } |
        Select-Object -First 1
    if (-not $line) {
        throw "Could not find version line in pyproject.toml"
    }
    return $matches[1]
}

if (-not $Version) {
    $Version = Read-VersionFromPyproject
}
Write-Host "Building Chika $Version..." -ForegroundColor Cyan

# ── Step 1: build the wheel ─────────────────────────────────────────────

if (-not $SkipWheel) {
    Write-Host "  · building wheel..." -ForegroundColor DarkGray
    Push-Location $RepoRoot
    try {
        # ``build`` is a PEP 517 frontend; less platform drift than
        # ``setup.py bdist_wheel`` and works from a stock Python.
        python -m pip install --upgrade build --quiet
        python -m build --wheel --outdir $WheelDir
    }
    finally {
        Pop-Location
    }
}

$wheel = Get-ChildItem -Path $WheelDir -Filter "chika-$Version-*.whl" |
    Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $wheel) {
    throw "No wheel found in $WheelDir matching chika-$Version-*.whl"
}
Write-Host "  · wheel: $($wheel.Name)" -ForegroundColor DarkGray

# ── Step 2: stage the build dir ─────────────────────────────────────────

if (Test-Path $BuildDir) {
    Remove-Item -Recurse -Force $BuildDir
}
$null = New-Item -ItemType Directory -Path "$BuildDir\source"
$null = New-Item -ItemType Directory -Path "$BuildDir\wheels"

# What ships in the installer's source tree. We deliberately exclude:
#   - tests/, e2e/                 (test code; not needed at runtime)
#   - .git*, .github/              (VCS / CI)
#   - node_modules/, dist/, build/ (build artefacts)
#   - __pycache__/, .pytest_cache/ (caches)
#   - frontend/, extension/        (shipped separately; the frontend
#                                   is bundled into the wheel via
#                                   pyproject's package_data when we
#                                   add that step in a future round)
$includeDirs  = @('chika', 'api', 'data', 'extension')
$includeFiles = @('chika.py', 'config.py', 'install.py', 'requirements.txt',
                   'pyproject.toml', 'README.md', 'LICENSE')

foreach ($d in $includeDirs) {
    $src = Join-Path $RepoRoot $d
    if (Test-Path $src) {
        Copy-Item -Recurse -Path $src -Destination "$BuildDir\source\$d" -Exclude '__pycache__','*.pyc','node_modules','test-results','playwright-report'
    }
}
foreach ($f in $includeFiles) {
    $src = Join-Path $RepoRoot $f
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination "$BuildDir\source\"
    }
}

# Clean nested __pycache__ that Copy-Item missed (recursive Exclude
# only applies to top-level matches in Powershell — known quirk).
Get-ChildItem -Path "$BuildDir\source" -Recurse -Force `
    -Include '__pycache__','*.pyc','.pytest_cache' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Copy LICENSE → LICENSE.txt for Inno (it expects a .txt extension).
$licenseSrc = Join-Path $RepoRoot 'LICENSE'
if (Test-Path $licenseSrc) {
    Copy-Item -Path $licenseSrc -Destination "$BuildDir\LICENSE.txt"
} else {
    # Fall back to a stub so the [Setup] LicenseFile= directive doesn't
    # 404 on the installer wizard.
    Set-Content -Path "$BuildDir\LICENSE.txt" -Value "MIT License (see github.com/tochi-mba/chika/blob/main/LICENSE)"
}

# Copy the wheel into the build dir.
Copy-Item -Path $wheel.FullName -Destination "$BuildDir\wheels\"

# Generate the install marker. ``chika update`` reads this to detect
# that we're a Windows-installer install and switch to the
# download-and-run-next-installer update path.
$marker = @{
    kind         = 'windows_installer'
    version      = $Version
    wheel        = $wheel.Name
    installed_at = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssZ')
} | ConvertTo-Json
Set-Content -Path "$BuildDir\install_marker.json" -Value $marker -Encoding UTF8

# ── Step 3: run Inno Setup ──────────────────────────────────────────────

if (-not (Test-Path $ISCC)) {
    throw @"
Inno Setup compiler not found at:
    $ISCC

Install Inno Setup 6 from https://jrsoftware.org/isdl.php, or pass a
custom path with -ISCC.
"@
}

if (-not (Test-Path $DistDir)) {
    $null = New-Item -ItemType Directory -Path $DistDir
}

Write-Host "  · running ISCC..." -ForegroundColor DarkGray
$iscArgs = @(
    "/DMyAppVersion=$Version",
    "/DSourceDir=$BuildDir",
    "/DWheelName=$($wheel.Name)",
    (Join-Path $InstallerDir 'chika.iss')
)
& $ISCC @iscArgs
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE"
}

$out = Join-Path $DistDir "chika-setup-$Version.exe"
if (-not (Test-Path $out)) {
    throw "Inno Setup ran but no output found at $out"
}

Write-Host ""
Write-Host "✓ installer ready: $out" -ForegroundColor Green
Write-Host "  size: $([math]::Round((Get-Item $out).Length / 1MB, 2)) MB" -ForegroundColor DarkGray
