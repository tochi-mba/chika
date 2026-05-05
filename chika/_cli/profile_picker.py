"""CLI profile-picker — runs before the main REPL boots.

We never start the REPL on the silent default profile any more. The user
picks (or creates) a profile, and if it has a password set we verify
it interactively before the engine loads. This makes the CLI behaviour
match the frontend / extension gates: every entry point requires an
explicit "I am this person" step.

The picker uses :mod:`getpass` for password entry so the typed text
isn't echoed back to the terminal. When stdin/stdout aren't TTYs (piped
input, e2e harness), passwords are read from stdin without echo
suppression — that's correct for tests but means scripted use should
prefer the unauthenticated default profile.
"""
from __future__ import annotations

import getpass
import sys
from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


_MAX_ATTEMPTS = 3


def _table_of_profiles(profiles: Iterable[str], password_marker) -> Table:
    """Build the rendered list — index, name, password badge."""
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="dim")
    t.add_column(style="bold")
    t.add_column(justify="right", style="dim")
    for i, name in enumerate(profiles, start=1):
        badge = "🔒" if password_marker(name) else " "
        t.add_row(f"{i}.", name, badge)
    return t


def select_profile(
    console: Console,
    profile_manager,
    *,
    accent: str,
):
    """Prompt the user to pick a profile and (if needed) authenticate.

    Returns the chosen :class:`Profile` ready to be handed to
    :meth:`ChikaEngine.switch_profile`. Exits the process on Ctrl+C.

    The picker supports four actions:
      - typing a number from the list
      - typing an existing profile name
      - typing ``new <name>`` to create one
      - typing ``q`` to abort
    """
    while True:
        names = profile_manager.list_profiles()
        if not names:
            # First-run bootstrap — drop straight into "create your first profile".
            console.print(Text(
                "  No profiles yet. Let's set one up.",
                style=accent,
            ))
            return _create_profile(console, profile_manager, accent=accent)

        console.print(
            Panel(
                _table_of_profiles(names, profile_manager.has_password),
                title=Text("  who's using chika?", style=accent),
                title_align="left",
                border_style=accent,
                padding=(1, 2),
                expand=False,
            )
        )
        console.print(Text(
            "  pick a number, type a name, `new <name>` to create, `q` to quit.",
            style="dim",
        ))

        try:
            raw = input("  › ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(Text("  · bye", style="dim"))
            sys.exit(0)

        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit"):
            console.print(Text("  · bye", style="dim"))
            sys.exit(0)
        if raw.lower().startswith("new "):
            wanted = raw[4:].strip()
            if not wanted:
                console.print(Text("  · usage: new <name>", style="yellow"))
                continue
            return _create_profile(
                console, profile_manager, name=wanted, accent=accent,
            )

        # Numeric index?
        chosen_name: str | None = None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(names):
                chosen_name = names[idx - 1]
        if chosen_name is None:
            # Match exactly or by case-insensitive name.
            for name in names:
                if name == raw or name.lower() == raw.lower():
                    chosen_name = name
                    break

        if chosen_name is None:
            console.print(Text(
                f"  · {raw!r} doesn't match any profile",
                style="yellow",
            ))
            continue

        if not profile_manager.has_password(chosen_name):
            return profile_manager.get_or_create(chosen_name)

        if _authenticate(console, profile_manager, chosen_name):
            return profile_manager.get_or_create(chosen_name)
        # _authenticate prints feedback; loop and let the user retry or pick.


def _create_profile(
    console: Console,
    profile_manager,
    *,
    name: str | None = None,
    accent: str,
):
    """Create a new profile, optionally with a password.

    The bootstrap path (no profiles exist yet) hits this with ``name=None``
    and prompts for everything; the explicit ``new foo`` flow comes in
    with ``name="foo"`` already set.
    """
    if name is None:
        try:
            name = input("  profile name › ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print(Text("  · bye", style="dim"))
            sys.exit(0)
        if not name:
            console.print(Text("  · profile name can't be empty", style="yellow"))
            return select_profile(console, profile_manager, accent=accent)

    if profile_manager.exists(name):
        console.print(Text(
            f"  · profile {name!r} already exists — picking instead",
            style="dim",
        ))
        if profile_manager.has_password(name):
            if not _authenticate(console, profile_manager, name):
                return select_profile(console, profile_manager, accent=accent)
        return profile_manager.get_or_create(name)

    profile = profile_manager.get_or_create(name)
    console.print(Text(
        f"  · profile {name!r} created.",
        style=accent,
    ))

    # Optional password.
    try:
        wants_pw = input("  set a password? [y/N] › ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return profile
    if wants_pw not in ("y", "yes"):
        return profile

    while True:
        try:
            pw1 = getpass.getpass("  password › ")
            pw2 = getpass.getpass("  confirm  › ")
        except (KeyboardInterrupt, EOFError):
            console.print(Text("  · keeping profile unprotected", style="dim"))
            return profile
        if not pw1:
            console.print(Text("  · empty password — skipping", style="dim"))
            return profile
        if pw1 != pw2:
            console.print(Text("  · passwords don't match — try again",
                               style="yellow"))
            continue
        profile_manager.set_password(name, pw1)
        console.print(Text(f"  · password set for {name!r}", style=accent))
        return profile


def _authenticate(console: Console, profile_manager, name: str) -> bool:
    """Prompt up to :data:`_MAX_ATTEMPTS` times. Returns True on success."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            pw = getpass.getpass(f"  password for {name!r} › ")
        except (KeyboardInterrupt, EOFError):
            return False
        if profile_manager.verify_password(name, pw):
            return True
        remaining = _MAX_ATTEMPTS - attempt
        if remaining:
            console.print(Text(
                f"  · wrong password — {remaining} attempt"
                f"{'s' if remaining != 1 else ''} left",
                style="yellow",
            ))
        else:
            console.print(Text(
                "  · too many attempts — pick a different profile",
                style="yellow",
            ))
    return False
