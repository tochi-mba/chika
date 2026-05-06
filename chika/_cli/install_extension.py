"""Install the bundled Chrome extension into the user's home directory.

Why this exists
---------------
Chrome MV3 has forbidden programmatic installs since 2014 — the only
two ways to load an extension are the Web Store and "Load unpacked"
in dev mode. Until Chika ships on the Web Store (see ADR-25), we can
at least automate the awkward bits of "Load unpacked":

  1. Copy the bundled ``extension/`` to a stable location
     (``~/.chika/extension/``) so the user can point Chrome at it
     once and never think about it again.
  2. Open ``chrome://extensions/`` in their default browser.
  3. Print a tight 3-step panel telling them what to click next.

The user still has to flip the dev-mode toggle and click "Load
unpacked" — but they no longer have to find the source dir, and
re-running this command refreshes their installed copy when we ship
a new build.

Source layout
-------------
We copy the *runtime* files only:

  manifest.json
  background.js
  content/, popup/, lib/, options/, icons/*.png

We deliberately skip:

  node_modules/             — Playwright deps; not needed at runtime
  e2e/                      — test specs
  test-results/             — Playwright traces
  playwright.config.js      — test runner config
  package.json, package-lock.json
  icons/_render.html, icons/_render.mjs, icons/generate_icons.js
                            — dev-only icon rasterisers

If a future build adds a new top-level runtime file we'll need to
update ``_RUNTIME_TOP_LEVEL_FILES`` / ``_RUNTIME_DIRS``. The icon
exclusion lives in ``_DIR_FILE_EXCLUDES`` so adding a new dev-only
helper there only takes one entry.
"""
from __future__ import annotations

import shutil
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


# Stable install destination — the same on every run. We blow it away
# and recopy on each invocation so stale files (e.g. an icon that was
# renamed in a release) don't linger.
EXTENSION_DEST: Path = Path.home() / ".chika" / "extension"

# What Chrome opens when the user clicks "Manage extensions". We can't
# load the unpacked extension for them (MV3 forbids it) but we can land
# them on the right page so step 1 is "toggle Developer mode" rather
# than "find the right setting".
CHROME_EXTENSIONS_URL = "chrome://extensions/"

# Top-level files inside ``extension/`` that ship with the runtime.
_RUNTIME_TOP_LEVEL_FILES: tuple[str, ...] = (
    "manifest.json",
    "background.js",
)

# Top-level dirs that ship with the runtime. Each gets walked
# recursively, with per-directory file exclusions applied.
_RUNTIME_DIRS: tuple[str, ...] = (
    "content",
    "popup",
    "lib",
    "options",
    "icons",
)

# Per-directory file blacklist. Entries are matched by *exact name*
# so a future ``icons/foo_render.png`` would still ship — only the
# specific dev helpers below are excluded.
_DIR_FILE_EXCLUDES: dict[str, frozenset[str]] = {
    "icons": frozenset({
        "_render.html",
        "_render.mjs",
        "generate_icons.js",
    }),
}


# ── Public API ────────────────────────────────────────────────────────────


def default_source() -> Path:
    """Return the bundled ``extension/`` dir relative to this package.

    ``chika/_cli/install_extension.py`` → ``../../extension`` from this
    file resolves to the repo root's ``extension/`` directory whether
    Chika is run from a clone, an editable install, or eventually a
    wheel that bundles the extension as package data.
    """
    return Path(__file__).resolve().parent.parent.parent / "extension"


def install_extension(
    source: Path | None = None,
    console: Console | None = None,
    *,
    dest: Path | None = None,
    open_browser: bool = True,
) -> Path:
    """Copy the runtime extension files to ``dest`` and open Chrome.

    Parameters
    ----------
    source
        Source ``extension/`` directory. Defaults to :func:`default_source`.
    console
        Rich console to render the post-install instruction panel onto.
        If ``None``, no panel is rendered (used in tests).
    dest
        Destination directory. Defaults to :data:`EXTENSION_DEST`.
        Tests pass a tmp_path here so the user's real ``~/.chika/`` is
        never touched.
    open_browser
        Whether to call :func:`webbrowser.open` with the chrome://
        extensions URL. Tests pass ``False`` to keep CI quiet.

    Returns
    -------
    Path
        The destination directory the extension was installed into.

    Raises
    ------
    FileNotFoundError
        If ``source`` doesn't exist or isn't a directory. We surface
        a clear error rather than silently creating an empty install.
    """
    src = (source or default_source()).resolve()
    if not src.is_dir():
        raise FileNotFoundError(
            f"extension source not found: {src} — expected the bundled "
            "extension/ directory next to chika.py",
        )

    dst = (dest or EXTENSION_DEST).resolve()
    _copy_runtime(src, dst)

    opened = False
    if open_browser:
        try:
            opened = bool(webbrowser.open(CHROME_EXTENSIONS_URL))
        except Exception:
            # Some sandboxed environments (CI, headless servers) don't
            # have a registered browser — that's fine, the panel still
            # tells the user where to point Chrome.
            opened = False

    if console is not None:
        _render_install_panel(console, dst, opened=opened)

    return dst


# ── Internals ─────────────────────────────────────────────────────────────


def _copy_runtime(src: Path, dst: Path) -> None:
    """Wipe ``dst`` and recopy the runtime subset of ``src`` into it.

    Wiping first means deleted files in a new release don't linger in
    the user's installed copy. Both ``rmtree`` and ``mkdir`` are
    idempotent so a fresh first install behaves the same as a re-run.
    """
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    for name in _RUNTIME_TOP_LEVEL_FILES:
        candidate = src / name
        if candidate.is_file():
            shutil.copy2(candidate, dst / name)

    for dirname in _RUNTIME_DIRS:
        sub_src = src / dirname
        if not sub_src.is_dir():
            continue
        sub_dst = dst / dirname
        excludes = _DIR_FILE_EXCLUDES.get(dirname, frozenset())
        _copy_tree(sub_src, sub_dst, exclude_names=excludes)


def _copy_tree(src: Path, dst: Path, *, exclude_names: frozenset[str]) -> None:
    """Recursive copy with per-name exclusions.

    Why not ``shutil.copytree(ignore=...)``: ``copytree`` errors when
    ``dst`` already exists on Python <3.8 and the ignore callback gets
    a list of mixed files+dirs that's awkward to filter. A 10-line
    explicit walk is clearer and lets us apply ``_DIR_FILE_EXCLUDES``
    precisely.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name in exclude_names:
            continue
        if entry.is_dir():
            _copy_tree(entry, dst / entry.name, exclude_names=frozenset())
        else:
            shutil.copy2(entry, dst / entry.name)


def _render_install_panel(console: Console, dest: Path, *, opened: bool) -> None:
    """Print the post-install 3-step instruction panel.

    Imports rich lazily so this module is importable in environments
    without rich (e.g. mypy under a stripped venv).
    """
    from rich.panel import Panel
    from rich.text import Text

    from chika._cli.renderer import THEME

    body = Text()
    body.append("extension copied to\n  ", style=THEME.muted)
    body.append(f"{dest}\n\n", style=f"bold {THEME.text}")

    if opened:
        body.append("opened ", style=THEME.muted)
        body.append(CHROME_EXTENSIONS_URL, style=f"bold {THEME.accent}")
        body.append(" in your default browser.\n", style=THEME.muted)
    else:
        body.append("open ", style=THEME.muted)
        body.append(CHROME_EXTENSIONS_URL, style=f"bold {THEME.accent}")
        body.append(" in Chrome.\n", style=THEME.muted)

    body.append("\nthen:\n", style=THEME.muted)
    body.append("  1. ", style=THEME.dim)
    body.append("toggle ", style=THEME.text)
    body.append("Developer mode", style=f"bold {THEME.accent}")
    body.append(" (top-right)\n", style=THEME.text)
    body.append("  2. ", style=THEME.dim)
    body.append("click ", style=THEME.text)
    body.append("Load unpacked", style=f"bold {THEME.accent}")
    body.append("\n", style=THEME.text)
    body.append("  3. ", style=THEME.dim)
    body.append("select the folder above\n", style=THEME.text)
    body.append("\nre-run ", style=THEME.muted)
    body.append("chika install-extension", style=f"italic {THEME.text}")
    body.append(" any time to refresh after an update.", style=THEME.muted)

    console.print(Panel(
        body,
        title=Text("install browser extension", style=f"bold {THEME.accent}"),
        title_align="left",
        border_style=THEME.accent,
        padding=(1, 2),
    ))
