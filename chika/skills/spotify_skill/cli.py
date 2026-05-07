"""
``chika spotify`` argv subcommand — connect / status / disconnect from
the terminal without booting the full REPL.

Usage:

    chika spotify connect            # open browser to authorize
    chika spotify connect --no-open  # print URL only (headless / SSH)
    chika spotify status             # show connection state
    chika spotify disconnect         # clear local tokens
    chika spotify share on|off       # toggle share-across-profiles

The slash-command equivalent inside the REPL lives in
``chika._cli.commands`` so users can drive the same flows mid-chat.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

USAGE = """\
chika spotify <command>

Commands:
  connect [--no-open]    start OAuth flow (opens browser by default)
  status                 print connection status
  disconnect             clear local tokens
  share on|off           toggle share-across-profiles
"""


def argv_factory(args: list[str]) -> int:
    """Auto-discovery entry: ``chika spotify <subcommand>``. Aliased
    here so the skill's CLI dispatch table key (``argv``) maps cleanly
    to the contract — but ``main(args)`` stays as an alias so any
    test / shim that imported it keeps working."""
    return main(args)


def slash_handler(args: list[str], **_kwargs) -> int:
    """``/spotify ...`` slash command inside the REPL. Same dispatch
    as the argv subcommand — ``args`` is the remainder after
    ``/spotify``."""
    return main(args)


def main(args: list[str]) -> int:
    if not args or args[0] in ("--help", "-h", "help"):
        print(USAGE)
        return 0

    # Re-read CHIKA_SPOTIFY_CLIENT_ID from the env right before
    # dispatching. ``oauth.CLIENT_ID`` was captured at module import
    # time; if the user updated their ``.env`` since, this picks up
    # the new value without a restart. Also defends against any
    # subtle import-order issue where ``oauth.py`` ran before the
    # parent CLI loaded ``.env``.
    try:
        from chika.skills.spotify_skill import oauth
        oauth.reload_from_env()
    except Exception:
        pass

    cmd, rest = args[0], args[1:]
    if cmd == "connect":
        return _connect(open_browser="--no-open" not in rest)
    if cmd == "status":
        return _status()
    if cmd == "disconnect":
        return _disconnect()
    if cmd == "share":
        if not rest or rest[0] not in ("on", "off"):
            print("chika spotify: share requires 'on' or 'off'", file=sys.stderr)
            return 2
        return _share(rest[0])
    print(f"chika spotify: unknown command {cmd!r}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


# ── Implementations ─────────────────────────────────────────────────────

def _connect(open_browser: bool) -> int:
    from chika.skills.spotify_skill import connection
    result = connection.start_connect(open_browser=open_browser)
    if result.get("error") == "no_client_id":
        print(_box(
            "Spotify isn't configured",
            result.get("message", ""),
            kind="error",
        ))
        return 1
    url = result.get("auth_url", "")
    opened = result.get("opened", False)
    if opened:
        print(_box(
            "Opening Spotify in your browser",
            "Sign in and click 'Agree' to connect Chika.\n"
            "After authorizing, this terminal will pick up the change\n"
            "automatically — leave Chika running.",
        ))
    else:
        print(_box(
            "Open this URL in your browser to connect Spotify",
            f"{url}\n\nAfter you authorize, this terminal will pick up\n"
            "the change automatically — leave Chika running.",
        ))
    return 0


def _status() -> int:
    from chika.skills.spotify_skill import connection
    s = connection.status()
    if not s.get("client_id_set"):
        print(_box(
            "Spotify isn't configured",
            "CLIENT_ID is missing. Set CHIKA_SPOTIFY_CLIENT_ID in your\n"
            "environment, or paste the Chika app's client_id into\n"
            "chika/skills/spotify_skill/oauth.py::_DEFAULT_CLIENT_ID.",
            kind="error",
        ))
        return 1
    if s["authorized"]:
        # Surface the user profile if we have it cached, else fetch.
        try:
            prof = asyncio.run(connection.fetch_profile())
        except Exception:
            prof = None
        name = (prof or {}).get("display_name", "—")
        product = (prof or {}).get("product", s.get("product", ""))
        bucket = "shared across all profiles" if s.get("shared") else f"profile: {s.get('profile')}"
        body = (
            f"Connected as {name}\n"
            f"Tier:    {product or 'unknown'}\n"
            f"Storage: {bucket}\n"
            f"Token:   {s.get('token_preview', '—')}"
        )
        print(_box("Spotify connected", body, kind="ok"))
        return 0
    if s.get("expired") or s.get("has_refresh"):
        print(_box(
            "Spotify token needs refresh",
            "Run `chika spotify connect` to re-authorize.",
        ))
        return 0
    print(_box(
        "Spotify not connected",
        "Run `chika spotify connect` to authorize.",
    ))
    return 0


def _disconnect() -> int:
    from chika.skills.spotify_skill import connection
    result = asyncio.run(connection.disconnect())
    print(_box(
        "Disconnected",
        result.get("message", "Tokens cleared."),
        kind="ok",
    ))
    return 0


def _share(mode: str) -> int:
    from api import settings_store
    settings_store.update({"spotify_share_across_profiles": mode})
    if mode == "on":
        body = (
            "Every Chika profile now shares one Spotify connection.\n"
            "Tokens live in the '_shared' bucket.\n\n"
            "If a profile was previously connected, you'll need to\n"
            "reconnect once — the per-profile tokens aren't migrated."
        )
    else:
        body = (
            "Each profile now keeps its own Spotify connection.\n"
            "Switch profile and run `chika spotify connect` per\n"
            "profile you want connected."
        )
    print(_box(f"Spotify sharing: {mode}", body, kind="ok"))
    return 0


# ── Pretty box helper ──────────────────────────────────────────────────
#
# Keep this module dep-free of `rich` so it works in plain-mode shells
# (the chika app falls back to plain when rich isn't installed). A
# hand-rolled unicode box reads well in the common terminals and isn't
# worth importing rich for.

def _box(title: str, body: str, kind: str = "info") -> str:
    sigil = {"ok": "✓", "error": "✗", "info": "·"}.get(kind, "·")
    width = max(
        max((len(line) for line in body.splitlines()), default=0),
        len(title) + 4,
    )
    width = min(max(width, 36), 78)

    def _row(s: str) -> str:
        return f"│ {s.ljust(width)} │"

    out = [f"┌{'─' * (width + 2)}┐"]
    out.append(_row(f"{sigil} {title}"))
    out.append(f"├{'─' * (width + 2)}┤")
    for line in body.splitlines():
        out.append(_row(line))
    out.append(f"└{'─' * (width + 2)}┘")
    return "\n".join(out)


def _format_args_for_help(parts: list[Any]) -> str:
    return " ".join(str(p) for p in parts)
