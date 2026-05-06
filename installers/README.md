# Chika installers

Native installers for each platform. The currently-shipping target is **Windows** (Inno Setup); macOS and Linux are scoped for the next round (see `macos/README.md` and `linux/README.md` for the planned approach).

## What an "installer" gets you

Beyond `pip install`:

- **Add/Remove Programs entry** — uninstall like a normal app
- **PATH integration** — `chika` works from any terminal
- **Per-user install** — no admin / sudo required
- **Auto-update path** — `chika update` knows it's an installer install and downloads the next setup.exe from GitHub Releases
- **User data preservation** — settings live in `~/.chika/data/` so they survive uninstall + reinstall

## Tree

```
installers/
├── README.md                  ← you are here
├── dist/                      ← build output (gitignored)
├── windows/
│   ├── chika.iss              ← Inno Setup script
│   ├── build_installer.ps1    ← orchestrates wheel + ISCC
│   ├── post_install.ps1       ← creates venv + pip installs wheel
│   ├── pre_uninstall.ps1      ← strips PATH entry, preserves user data
│   ├── chika.cmd              ← on-PATH launcher (sets CHIKA_DATA_DIR)
│   └── chika.ico              ← (placeholder; regenerate from Vue mark)
├── macos/
│   └── README.md              ← .pkg approach for next round
└── linux/
    └── README.md              ← .deb / AppImage for next round
```

## Building locally (Windows)

Requires:

- Python 3.11+
- [Inno Setup 6](https://jrsoftware.org/isdl.php)
- PowerShell 5.1+ (ships with Windows)

```powershell
.\installers\windows\build_installer.ps1
```

Output: `installers/dist/chika-setup-X.Y.Z.exe`. Version is read from `pyproject.toml`. Pass `-Version 2.0.5` to override.

## Building in CI

`.github/workflows/release.yml` triggers on tags like `v2.0.5`:

1. Builds a wheel on Linux (smaller image, faster)
2. Hands it to a Windows runner that runs Inno Setup
3. Creates a GitHub Release with both attached

## Auto-update integration

`chika/_cli/update.py::detect_install_kind` looks for `install_marker.json` next to the venv. The Windows installer drops one with `{"kind": "windows_installer", "version": "..."}` so:

- `chika update` knows to download the next `chika-setup-X.Y.Z.exe` from GitHub Releases and run it silently with `/SILENT /SUPPRESSMSGBOXES`
- Auto-update on startup (the daemon thread in `_run_rich`) does the same when `auto_update` is on and there's a newer release

The full design lives in [DECISIONS.md ADR-30](../DECISIONS.md).

## Code signing

Currently unsigned — Windows SmartScreen will warn on first run ("Windows protected your PC"). For a proper release we'd want:

- Windows: Authenticode certificate from a CA, sign `chika-setup-*.exe` and `chika.cmd` (via `signtool.exe`)
- macOS: Apple Developer ID certificate, sign + notarise the `.pkg`
- Linux: GPG sign the `.deb` / verify checksums on the AppImage

Out of scope for this round; tracked separately.
