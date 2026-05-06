"""``chika setup`` — interactive first-run wizard.

Wraps ``install.py``'s wizard so users who installed via the native
installer (or any other route that doesn't run install.py) can still
get the same provider-picking, API-key-entering, ``.env``-writing
guided experience.

Edge cases handled:

  - .env already exists with content → refuse to overwrite without
    ``--force`` (running setup twice shouldn't silently clobber
    working credentials).
  - Python below 3.11 → fail clearly *before* asking for an API key
    that wouldn't help.
  - Non-TTY stdin (piped, CI, GUI subprocess) → refuse to run; the
    wizard needs interactive input.
  - install.py module not on disk (corrupted install) → error with
    the manual command the user can run by hand.

The wizard itself lives at ``install.py``; we delegate to its
``main()`` function. That keeps the dev install flow (``python
install.py`` from a clone) and the setup-after-install flow
(``chika setup``) on a single code path.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(frozen=True)
class SetupResult:
    success: bool
    message: str


def run_setup(
    console: Console | None = None,
    *,
    force: bool = False,
    repo_root: Path | None = None,
    is_tty: bool | None = None,
) -> SetupResult:
    """Run the interactive setup wizard.

    Parameters
    ----------
    console
        Optional rich console for diagnostic output.
    force
        Allow overwriting an existing non-empty ``.env``.
    repo_root
        Override the search path for ``install.py``. Defaults to two
        parents up from this file (the project root).
    is_tty
        Override the TTY detection (tests inject ``True`` even when
        pytest is capturing stdout).
    """
    if is_tty is None:
        is_tty = sys.stdin.isatty() and sys.stdout.isatty()

    if not is_tty:
        result = SetupResult(
            success=False,
            message=(
                "setup wizard needs an interactive terminal — stdin/stdout\n"
                "  must be a TTY. Run from a real terminal, not piped or in CI."
            ),
        )
        _maybe_render(console, result)
        return result

    # pyproject already enforces 3.11+, but this check is a runtime
    # safety net for users running an installed chika under an older
    # Python somehow (mismatched venv, broken install).
    if sys.version_info[:2] < (3, 11):  # noqa: UP036
        result = SetupResult(
            success=False,
            message=(
                f"Python 3.11+ required (you have {sys.version_info.major}."
                f"{sys.version_info.minor}). install a newer Python and re-run."
            ),
        )
        _maybe_render(console, result)
        return result

    root = (repo_root or _default_repo_root()).resolve()
    env_path = root / ".env"
    if env_path.exists() and env_path.stat().st_size > 0 and not force:
        result = SetupResult(
            success=False,
            message=(
                f".env already exists at {env_path} (and isn't empty).\n"
                "  re-run setup with --force to overwrite, or edit .env\n"
                "  manually. you can also change provider / API key any\n"
                "  time from inside chika via /provider and /env."
            ),
        )
        _maybe_render(console, result)
        return result

    install_py = root / "install.py"
    if not install_py.is_file():
        result = SetupResult(
            success=False,
            message=(
                f"install.py not found at {install_py}.\n"
                "  this is unexpected — your install may be corrupted.\n"
                "  reinstall from https://github.com/tochi-mba/chika/releases"
            ),
        )
        _maybe_render(console, result)
        return result

    # Dynamic import so we don't add ``install`` to the package
    # namespace for processes that never call setup.
    spec = importlib.util.spec_from_file_location("_chika_install", install_py)
    if spec is None or spec.loader is None:
        return SetupResult(
            success=False,
            message=f"could not load {install_py} (importlib spec is None).",
        )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        result = SetupResult(
            success=False, message=f"install.py failed to import: {exc}",
        )
        _maybe_render(console, result)
        return result

    main = getattr(mod, "main", None)
    if not callable(main):
        result = SetupResult(
            success=False,
            message="install.py has no callable main() — corrupted install.",
        )
        _maybe_render(console, result)
        return result

    try:
        main()
    except KeyboardInterrupt:
        return SetupResult(
            success=False,
            message="setup cancelled.",
        )
    except SystemExit as exc:
        if exc.code in (0, None):
            return SetupResult(success=True, message="setup complete.")
        return SetupResult(
            success=False,
            message=f"setup wizard exited with code {exc.code}.",
        )
    except Exception as exc:
        return SetupResult(
            success=False, message=f"setup wizard raised: {exc}",
        )

    return SetupResult(success=True, message="setup complete.")


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _maybe_render(console: Console | None, result: SetupResult) -> None:
    if console is None:
        return
    from rich.text import Text

    from chika._cli.renderer import THEME
    style = THEME.success if result.success else THEME.error
    console.print(Text(f"  · {result.message}", style=style))


# ── First-run hook ───────────────────────────────────────────────────────


def needs_first_run_setup(repo_root: Path | None = None) -> bool:
    """True iff the runtime can't find a usable ``.env`` config.

    Used by ``app.py`` on REPL boot to surface a one-line "run setup?"
    nudge. Cheap (just a stat); never raises.
    """
    root = (repo_root or _default_repo_root()).resolve()
    env_path = root / ".env"
    if not env_path.is_file():
        return True
    try:
        return env_path.stat().st_size == 0
    except Exception:
        return False


def render_first_run_nudge(console: Console) -> None:
    """One-line friendly prompt printed during REPL boot when .env is missing."""
    from rich.text import Text

    from chika._cli.renderer import THEME

    line = Text("  ", style=THEME.muted)
    line.append("first-run? ", style=f"bold {THEME.accent}")
    line.append("provider + API key not configured. ", style=THEME.text)
    line.append("run ", style=THEME.muted)
    line.append("/setup", style=f"bold {THEME.accent}")
    line.append(" to launch the wizard, or set ", style=THEME.muted)
    line.append("CHIKA_PROVIDER", style=f"italic {THEME.text}")
    line.append(" + the matching API key env var.\n  ", style=THEME.muted)
    line.append("settings can be changed any time with /provider, /env, /settings.",
                style=THEME.dim)
    console.print(line)
