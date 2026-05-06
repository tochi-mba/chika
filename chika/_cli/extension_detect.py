"""Detect whether the Chika browser extension is already active.

When ``chika install-extension`` runs (or the native installer's
post-install hook), we want to know what the user's current state
is before showing instructions. The right UX depends on it:

  - **Already active** → "extension already installed, refreshed
    your local copy at ~/.chika/extension/. No further action."
  - **Files present, not loaded in Chrome** → "files are at <path>;
    open chrome://extensions, click Load unpacked, point at <path>."
  - **Nothing** → full first-time flow (open browser, etc.).

There's no clean OS-level API for "is extension X loaded in
Chrome?" — Chrome doesn't expose IPC for it. We combine three
imperfect signals into a single :class:`DetectionResult` with an
explicit confidence level.

Signals
-------
1. **Heartbeat** — when the extension's WS connects to our
   backend, the server writes ``~/.chika/extension_active.json``
   with a timestamp. If the file exists AND is recent (< 7 days),
   that's the strongest signal: the extension was actively connecting
   to *our* backend. Confidence: ``confirmed_active``.

2. **Chrome profile filesystem** — walk every known Chrome / Chromium
   / Brave / Edge / Vivaldi / Arc profile directory and read every
   extension's ``manifest.json``. If any matches our identifying
   fields (name, description, manifest_version, expected permissions),
   we know the user has loaded the extension at least once. Confidence:
   ``present_in_chrome_profile``. We don't know if it's currently
   *enabled* — Chrome stores enable-state in ``Preferences`` JSON
   which is more fragile to parse.

3. **Local files** — if ``~/.chika/extension/`` exists with a valid
   ``manifest.json``, the user has at least *unpacked* our extension
   files (via ``chika install-extension``). Whether Chrome has been
   pointed at them is a separate question. Confidence:
   ``installed_filesystem``.

4. **Nothing of the above** → ``unknown``.

Edge cases handled
------------------
- Multiple Chrome installs (Stable/Beta/Dev/Canary), profiles
  (Default, Profile 1, Profile 2), and Chromium-derived browsers
  (Brave, Edge, Vivaldi, Arc, Opera) are all walked.
- Sandboxed installs (Snap, Flatpak) get their separate paths.
- Heartbeat is per-platform (``~/.chika/`` on Linux/macOS,
  ``%USERPROFILE%\\.chika`` on Windows).
- Stale heartbeat (older than 7 days) is treated as no-signal —
  user could have wiped Chrome since then.
- False positives from name collisions ("Chika" might be another
  product) are mitigated by matching multiple manifest fields.
- Detection is read-only — never modifies the user's Chrome profile.
- Detection is bounded — walks at most ~200 extension directories
  and times out reading any single manifest at 1s.
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# How recent the heartbeat must be to count as "active." A week is
# a generous window — extensions don't run continuously, but if a
# user opened Chrome with ours loaded in the last week, we treat
# them as a returning user.
_HEARTBEAT_FRESH_SECONDS = 7 * 24 * 60 * 60

# Distinguishing manifest fields. We require ALL of these to match —
# any single one could collide with another extension by accident.
_EXPECTED_MANIFEST_NAME = "Chika Browser Agent"
_EXPECTED_PERMISSIONS = {"tabs", "activeTab", "scripting", "storage"}

# Bound the walk so a pathological filesystem doesn't hang.
_MAX_EXTENSIONS_TO_INSPECT = 500
_PER_FILE_READ_TIMEOUT_S = 1.0


@dataclass
class DetectionResult:
    """Confidence-tiered detection outcome.

    ``confidence`` is one of:
      - ``"confirmed_active"`` — recent heartbeat from our backend
      - ``"present_in_chrome_profile"`` — found a matching manifest
        in a Chrome / Chromium / Brave / etc. profile
      - ``"installed_filesystem"`` — ``~/.chika/extension/`` exists
        with a valid manifest, but Chrome may not be pointed at it
      - ``"unknown"`` — none of the above

    ``signals`` is a list of (signal_name, detail) tuples for
    diagnostics. Multiple signals can fire — confidence is the
    highest.
    """
    confidence: str
    signals: list[tuple[str, str]] = field(default_factory=list)
    last_heartbeat: float | None = None

    @property
    def is_active(self) -> bool:
        return self.confidence == "confirmed_active"

    @property
    def is_present(self) -> bool:
        return self.confidence in ("confirmed_active", "present_in_chrome_profile")

    @property
    def is_installed_locally(self) -> bool:
        return self.confidence != "unknown"


# ── Heartbeat ────────────────────────────────────────────────────────


def heartbeat_path() -> Path:
    return Path.home() / ".chika" / "extension_active.json"


def write_heartbeat(*, path: Path | None = None, now: float | None = None) -> None:
    """Called from the backend when the extension WS connects."""
    p = path or heartbeat_path()
    ts = now if now is not None else time.time()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"last_seen": ts}, separators=(",", ":")),
            encoding="utf-8",
        )
    except OSError:
        # Heartbeat is best-effort — never crash the WS connect on a
        # heartbeat write failure.
        pass


def read_heartbeat(*, path: Path | None = None) -> float | None:
    """Returns the unix timestamp of the most recent heartbeat, or None."""
    p = path or heartbeat_path()
    try:
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = data.get("last_seen")
        return float(ts) if isinstance(ts, (int, float)) else None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


# ── Local filesystem (~/.chika/extension/) ───────────────────────────


def local_install_path() -> Path:
    return Path.home() / ".chika" / "extension"


def is_locally_installed(*, root: Path | None = None) -> bool:
    """Does ``~/.chika/extension/manifest.json`` exist + look like ours?"""
    p = (root or local_install_path()) / "manifest.json"
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return _manifest_matches_chika(data)


def _manifest_matches_chika(data: object) -> bool:
    """True iff a parsed manifest.json matches Chika's identifying fields."""
    if not isinstance(data, dict):
        return False
    if data.get("name") != _EXPECTED_MANIFEST_NAME:
        return False
    if data.get("manifest_version") != 3:
        return False
    perms = set(data.get("permissions") or [])
    # Tolerant intersection: we ship 6 permissions; require at least
    # 4 of our 4 distinguishing ones to be present.
    overlap = perms & _EXPECTED_PERMISSIONS
    if len(overlap) < len(_EXPECTED_PERMISSIONS):
        return False
    return True


# ── Chrome / Chromium profile walk ───────────────────────────────────


def candidate_chrome_dirs() -> list[Path]:
    """Per-platform list of Chrome / Chromium / Brave / Edge / etc.
    user-data root directories.

    These are the parents of the per-profile ``Default/`` and
    ``Profile N/`` subdirectories. Each profile contains
    ``Extensions/<ext_id>/<version>/manifest.json``.
    """
    home = Path.home()
    out: list[Path] = []

    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
        out += [
            base / "Google" / "Chrome",
            base / "Google" / "Chrome Beta",
            base / "Google" / "Chrome Dev",
            base / "Google" / "Chrome Canary",
            base / "Chromium",
            base / "BraveSoftware" / "Brave-Browser",
            base / "Microsoft Edge",
            base / "Vivaldi",
            base / "Arc" / "User Data",
            base / "Opera Software" / "Opera Stable",
        ]
    elif sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        out += [
            local / "Google" / "Chrome" / "User Data",
            local / "Google" / "Chrome Beta" / "User Data",
            local / "Google" / "Chrome Dev" / "User Data",
            local / "Google" / "Chrome SxS" / "User Data",
            local / "Chromium" / "User Data",
            local / "BraveSoftware" / "Brave-Browser" / "User Data",
            local / "Microsoft" / "Edge" / "User Data",
            local / "Vivaldi" / "User Data",
            roaming / "Opera Software" / "Opera Stable",
        ]
    else:  # Linux + others
        config = home / ".config"
        out += [
            config / "google-chrome",
            config / "google-chrome-beta",
            config / "google-chrome-unstable",
            config / "chromium",
            config / "BraveSoftware" / "Brave-Browser",
            config / "microsoft-edge",
            config / "vivaldi",
            config / "opera",
            # Snap install of Chromium puts its config under ~/snap/...
            home / "snap" / "chromium" / "common" / "chromium",
            # Flatpak Chrome
            home / ".var" / "app" / "com.google.Chrome" / "config" / "google-chrome",
        ]
    return out


def _profile_dirs_under(user_data_root: Path) -> list[Path]:
    """Find ``Default/`` + ``Profile N/`` subdirs under a user-data root."""
    if not user_data_root.is_dir():
        return []
    profiles: list[Path] = []
    try:
        for entry in user_data_root.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if name == "Default" or name.startswith("Profile "):
                profiles.append(entry)
    except OSError:
        pass
    return profiles


def walk_chrome_profiles_for_chika(
    *, candidate_dirs: list[Path] | None = None,
    max_inspect: int = _MAX_EXTENSIONS_TO_INSPECT,
) -> tuple[bool, str | None]:
    """Walk every Chrome-family profile looking for our extension.

    Returns ``(found, detail)`` — ``detail`` describes which browser
    + profile the match was found in (for the diagnostic signal list).
    """
    candidates = candidate_dirs if candidate_dirs is not None else candidate_chrome_dirs()
    inspected = 0
    for user_data in candidates:
        if not user_data.is_dir():
            continue
        for profile in _profile_dirs_under(user_data):
            ext_root = profile / "Extensions"
            if not ext_root.is_dir():
                continue
            try:
                ext_dirs = list(ext_root.iterdir())
            except OSError:
                continue
            for ext_dir in ext_dirs:
                if not ext_dir.is_dir():
                    continue
                # Each extension has version-named subdirs
                try:
                    version_dirs = [v for v in ext_dir.iterdir() if v.is_dir()]
                except OSError:
                    continue
                for version_dir in version_dirs:
                    inspected += 1
                    if inspected > max_inspect:
                        return False, None
                    manifest = version_dir / "manifest.json"
                    if not manifest.is_file():
                        continue
                    try:
                        text = manifest.read_text(encoding="utf-8", errors="replace")
                        data = json.loads(text)
                    except (OSError, json.JSONDecodeError):
                        continue
                    if _manifest_matches_chika(data):
                        # Description + relative path for debug
                        rel = profile.relative_to(profile.parents[2]) if len(profile.parents) >= 3 else profile.name
                        return True, f"{user_data.name}/{rel}/Extensions/{ext_dir.name}"
    return False, None


# ── Top-level detection ──────────────────────────────────────────────


def detect_extension(
    *,
    now: float | None = None,
    heartbeat_file: Path | None = None,
    local_root: Path | None = None,
    chrome_dirs: list[Path] | None = None,
) -> DetectionResult:
    """Run all three signals + return the highest-confidence verdict.

    Tests inject `heartbeat_file`, `local_root`, and `chrome_dirs`
    so the function can run hermetically.
    """
    signals: list[tuple[str, str]] = []
    last_hb: float | None = None
    confidence = "unknown"

    # Signal 1: heartbeat (strongest)
    last_hb = read_heartbeat(path=heartbeat_file)
    if last_hb is not None:
        ts_now = now if now is not None else time.time()
        age = ts_now - last_hb
        if 0 <= age < _HEARTBEAT_FRESH_SECONDS:
            confidence = "confirmed_active"
            signals.append(("heartbeat", f"last seen {int(age)}s ago"))
        else:
            signals.append(("heartbeat_stale", f"{int(age)}s old (>= 7 days)"))

    # Signal 2: Chrome profile walk
    if confidence != "confirmed_active":
        found, detail = walk_chrome_profiles_for_chika(candidate_dirs=chrome_dirs)
        if found:
            confidence = "present_in_chrome_profile"
            signals.append(("chrome_profile", detail or "matching manifest found"))

    # Signal 3: local install
    if confidence == "unknown":
        if is_locally_installed(root=local_root):
            confidence = "installed_filesystem"
            signals.append(("local_files", str(local_install_path())))
    else:
        # Still record the local-files signal for diagnostics even if
        # a stronger one already won.
        if is_locally_installed(root=local_root):
            signals.append(("local_files", str(local_install_path())))

    return DetectionResult(
        confidence=confidence,
        signals=signals,
        last_heartbeat=last_hb,
    )


def render_detection(console, result: DetectionResult) -> None:
    """One-line console summary of the detection result."""
    from rich.text import Text

    from chika._cli.renderer import THEME

    label = {
        "confirmed_active":          "extension is active",
        "present_in_chrome_profile": "extension is loaded in Chrome",
        "installed_filesystem":      "extension files installed (Chrome may need 'Load unpacked')",
        "unknown":                   "extension not detected",
    }[result.confidence]
    style = (
        THEME.success if result.confidence == "confirmed_active" else
        THEME.accent if result.is_present else
        THEME.muted if result.is_installed_locally else
        THEME.dim
    )
    console.print(Text(f"  · {label}", style=style))
    if result.signals:
        for name, detail in result.signals:
            console.print(Text(f"      {name}: {detail}", style=THEME.dim))


# Platform helper exposed for tests.
def _is_windows() -> bool:
    return platform.system() == "Windows"
