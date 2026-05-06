"""``chika uninstall`` — remove Chika cleanly.

Detection mirrors :mod:`chika._cli.update`: we figure out the install
kind, then either invoke the right uninstaller or print exact
instructions for the OS's app manager.

Per-kind behaviour:

  ``git_clone``
      Run ``pip uninstall -y chika`` (the editable install). The cloned
      repo itself is left alone — it's the user's working copy, not
      something we should silently delete. Print a one-liner the user
      can paste to ``rm -rf`` the clone if they want it gone.

  ``pip_pypi``
      Run ``pip uninstall -y chika``.

  ``windows_installer``
      Locate the unins000.exe Inno generated and either run it
      silently or, when ``yes=False``, point the user at Add/Remove
      Programs (which is what most Windows users expect to use).

  ``macos_installer``
      Invoke ``/Library/Application Support/Chika/uninstall.sh``. We
      can't bypass sudo from inside Python, so we ``exec`` it via
      ``sudo``-prefixed command and let the user authenticate.

  ``linux_deb``
      Run ``sudo apt-get remove -y chika`` (or ``dpkg -r chika`` as
      fallback when apt isn't on PATH — fringe but possible).

  ``linux_universal``
      Run ``~/.local/share/chika/uninstall.sh``.

  ``unknown``
      Print the matrix of possible uninstall commands and let the
      user pick.

User data preservation
----------------------
By default we leave ``~/.chika/`` (settings, profiles, chat history)
untouched. Pass ``--remove-data`` to wipe it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(frozen=True)
class UninstallResult:
    kind: str
    success: bool
    message: str


def uninstall_chika(
    console: Console | None = None,
    *,
    yes: bool = False,
    remove_data: bool = False,
    dry_run: bool = False,
    runner=None,
) -> UninstallResult:
    """Remove Chika according to the detected install kind.

    Parameters
    ----------
    console
        Optional rich console for output rendering.
    yes
        If True, run the appropriate uninstaller without prompting.
        If False (default), print instructions and do nothing.
    remove_data
        If True, also wipe ``~/.chika/``.
    dry_run
        Skip the actual subprocess calls (test hook).
    runner
        Subprocess injection for tests.

    Returns
    -------
    UninstallResult
        ``success=True`` means the uninstall command ran cleanly OR
        we successfully delivered instructions to the user. The
        ``yes=False`` path always returns success because the user
        hasn't been promised anything beyond instructions.
    """
    from chika._cli.update import detect_install_kind  # avoid import cycle
    kind = detect_install_kind()
    run = runner or _run

    if kind == "git_clone":
        result = _uninstall_git_clone(yes=yes, dry_run=dry_run, run=run)
    elif kind == "pip_pypi":
        result = _uninstall_pip(yes=yes, dry_run=dry_run, run=run)
    elif kind == "windows_installer":
        result = _uninstall_windows(yes=yes, dry_run=dry_run, run=run)
    elif kind == "macos_installer":
        result = _uninstall_macos(yes=yes, dry_run=dry_run, run=run)
    elif kind == "linux_deb":
        result = _uninstall_deb(yes=yes, dry_run=dry_run, run=run)
    elif kind == "linux_universal":
        result = _uninstall_linux_universal(yes=yes, dry_run=dry_run, run=run)
    else:
        result = UninstallResult(
            kind="unknown", success=False,
            message=(
                "couldn't detect how Chika was installed. Try one of:\n"
                "  · pip install     →  pip uninstall chika\n"
                "  · Windows .exe    →  Settings → Apps → Chika → Uninstall\n"
                "  · macOS .pkg      →  sudo /Library/Application\\ Support/Chika/uninstall.sh\n"
                "  · Linux .deb      →  sudo apt remove chika\n"
                "  · curl install.sh →  ~/.local/share/chika/uninstall.sh"
            ),
        )

    if remove_data and result.success and not dry_run:
        _wipe_user_data()

    if console is not None:
        _render(console, result, removed_data=remove_data)
    return result


# ── Per-kind handlers ────────────────────────────────────────────────────


def _uninstall_pip(*, yes: bool, dry_run: bool, run) -> UninstallResult:
    if not yes:
        return UninstallResult(
            kind="pip_pypi", success=True,
            message="run: pip uninstall -y chika",
        )
    if dry_run:
        return UninstallResult(
            kind="pip_pypi", success=True,
            message="dry-run: would pip uninstall -y chika",
        )
    proc = run([sys.executable, "-m", "pip", "uninstall", "-y", "chika"])
    if proc.returncode != 0:
        return UninstallResult(
            kind="pip_pypi", success=False,
            message=f"pip uninstall failed: {(proc.stderr or proc.stdout).strip().splitlines()[-1] if (proc.stderr or proc.stdout).strip() else proc.returncode}",
        )
    return UninstallResult(
        kind="pip_pypi", success=True,
        message="pip uninstall complete.",
    )


def _uninstall_git_clone(*, yes: bool, dry_run: bool, run) -> UninstallResult:
    """Same as pip uninstall but also tells the user about the clone dir."""
    base = _uninstall_pip(yes=yes, dry_run=dry_run, run=run)
    if not base.success:
        return UninstallResult(
            kind="git_clone", success=False, message=base.message,
        )
    from chika._cli.update import REPO_ROOT
    note = f"\n  · the cloned repo at {REPO_ROOT} is untouched.\n    delete it manually with: rm -rf {REPO_ROOT}"
    return UninstallResult(
        kind="git_clone", success=True, message=base.message + note,
    )


def _uninstall_windows(*, yes: bool, dry_run: bool, run) -> UninstallResult:
    """Find unins000.exe Inno generated and run it (silently if yes=True)."""
    install_dir = _resolve_install_dir()
    unins = install_dir / "unins000.exe" if install_dir else None
    if unins is None or not unins.is_file():
        return UninstallResult(
            kind="windows_installer", success=True,
            message=(
                "open Settings → Apps → Installed apps → search 'Chika' → "
                "click '...' → Uninstall.\n"
                "  (the Add/Remove Programs entry is the standard way "
                "to uninstall a Windows app.)"
            ),
        )
    if not yes:
        return UninstallResult(
            kind="windows_installer", success=True,
            message=(
                f"run:  {unins}  /SILENT\n"
                "  or use Settings → Apps → Installed apps → Chika → Uninstall."
            ),
        )
    if dry_run:
        return UninstallResult(
            kind="windows_installer", success=True,
            message=f"dry-run: would run {unins} /SILENT /SUPPRESSMSGBOXES",
        )
    proc = run([str(unins), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    if proc.returncode != 0:
        return UninstallResult(
            kind="windows_installer", success=False,
            message=f"uninstaller exited with code {proc.returncode}",
        )
    return UninstallResult(
        kind="windows_installer", success=True,
        message="Windows uninstaller ran.",
    )


def _uninstall_macos(*, yes: bool, dry_run: bool, run) -> UninstallResult:
    script = Path("/Library/Application Support/Chika/uninstall.sh")
    if not script.is_file():
        return UninstallResult(
            kind="macos_installer", success=True,
            message=(
                "uninstall script not found at /Library/Application Support/Chika/uninstall.sh.\n"
                "  did you install via the .pkg? If you used pip / curl install.sh,\n"
                "  re-run `chika uninstall` from inside that environment."
            ),
        )
    if not yes:
        return UninstallResult(
            kind="macos_installer", success=True,
            message=f"run:  sudo {script}",
        )
    if dry_run:
        return UninstallResult(
            kind="macos_installer", success=True,
            message=f"dry-run: would sudo {script}",
        )
    proc = run(["sudo", str(script)])
    if proc.returncode != 0:
        return UninstallResult(
            kind="macos_installer", success=False,
            message=f"uninstall.sh exited with code {proc.returncode}",
        )
    return UninstallResult(
        kind="macos_installer", success=True,
        message="Chika uninstalled.",
    )


def _uninstall_deb(*, yes: bool, dry_run: bool, run) -> UninstallResult:
    apt = shutil.which("apt-get") or shutil.which("apt")
    if not yes:
        cmd = "sudo apt remove -y chika" if apt else "sudo dpkg -r chika"
        return UninstallResult(
            kind="linux_deb", success=True, message=f"run:  {cmd}",
        )
    if dry_run:
        return UninstallResult(
            kind="linux_deb", success=True,
            message="dry-run: would sudo apt remove -y chika",
        )
    if apt:
        proc = run(["sudo", apt, "remove", "-y", "chika"])
    else:
        proc = run(["sudo", "dpkg", "-r", "chika"])
    if proc.returncode != 0:
        return UninstallResult(
            kind="linux_deb", success=False,
            message=f"package manager exited with code {proc.returncode}",
        )
    return UninstallResult(
        kind="linux_deb", success=True, message="apt remove complete.",
    )


def _uninstall_linux_universal(*, yes: bool, dry_run: bool, run) -> UninstallResult:
    script = Path.home() / ".local" / "share" / "chika" / "uninstall.sh"
    if not script.is_file():
        return UninstallResult(
            kind="linux_universal", success=True,
            message=(
                "uninstall script not found.\n"
                "  remove manually:\n"
                "    rm -rf ~/.local/share/chika\n"
                "    rm -f ~/.local/bin/chika"
            ),
        )
    if not yes:
        return UninstallResult(
            kind="linux_universal", success=True,
            message=f"run:  {script}",
        )
    if dry_run:
        return UninstallResult(
            kind="linux_universal", success=True,
            message=f"dry-run: would run {script}",
        )
    proc = run(["bash", str(script)])
    if proc.returncode != 0:
        return UninstallResult(
            kind="linux_universal", success=False,
            message=f"uninstall.sh exited with code {proc.returncode}",
        )
    return UninstallResult(
        kind="linux_universal", success=True, message="Chika uninstalled.",
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _resolve_install_dir() -> Path | None:
    """Walk up from sys.prefix looking for install_marker.json."""
    candidates = [Path(sys.prefix).parent, Path(sys.prefix)]
    for p in candidates:
        if (p / "install_marker.json").is_file():
            return p
    return None


def _wipe_user_data() -> None:
    user_dir = Path.home() / ".chika"
    if user_dir.is_dir():
        shutil.rmtree(user_dir, ignore_errors=True)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _render(console: Console, result: UninstallResult, *, removed_data: bool) -> None:
    from rich.panel import Panel
    from rich.text import Text

    from chika._cli.renderer import THEME

    title_style = THEME.success if result.success else THEME.error
    title = ("uninstall" if result.success else "uninstall failed")

    body = Text()
    body.append("install kind: ", style=THEME.muted)
    body.append(f"{result.kind}\n\n", style=f"bold {THEME.text}")
    body.append(result.message, style=THEME.text)

    # Browser-extension reminder. We can't reach into Chrome's profile
    # to remove the loaded extension, so we surface what we detected
    # and tell the user what to do.
    try:
        from chika._cli.extension_detect import detect_extension
        det = detect_extension()
    except Exception:
        det = None
    if det is not None and det.is_present:
        body.append(
            "\n\nthe browser extension is still loaded in your browser.\n"
            "  finish the uninstall by opening ",
            style=THEME.warn,
        )
        body.append("chrome://extensions/", style=f"bold {THEME.accent}")
        body.append(", finding ", style=THEME.warn)
        body.append("Chika Browser Agent", style=f"bold {THEME.text}")
        body.append(", and clicking ", style=THEME.warn)
        body.append("Remove", style=f"bold {THEME.text}")
        body.append(".", style=THEME.warn)

    if removed_data:
        body.append("\n\nuser data at ~/.chika/ wiped.", style=THEME.warn)
    else:
        body.append(
            "\n\nuser data at ~/.chika/ preserved (settings, profiles, "
            "chat history).\n  re-run with --remove-data to wipe.",
            style=THEME.muted,
        )
    console.print(Panel(
        body,
        title=Text(title, style=f"bold {title_style}"),
        title_align="left",
        border_style=title_style,
        padding=(1, 2),
    ))


# Make ``os`` reachable on the module so tests can monkeypatch
# environment variables without importing it themselves.
__all__ = [
    "UninstallResult",
    "uninstall_chika",
]
_ = os  # silence "imported but unused" without removing the import
