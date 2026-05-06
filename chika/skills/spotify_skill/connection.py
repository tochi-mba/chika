"""
High-level Spotify connection helpers — the layer the UI / CLI calls.

The OAuth primitives in :mod:`oauth` are intentionally low-level: build
the URL, exchange the code, refresh the token. This module sits on top
and gives the rest of the app a one-call surface:

    >>> from chika.skills.spotify_skill import connection
    >>> connection.start_connect()      # → opens browser, returns connect URL
    >>> connection.status()             # → connected | connecting | disconnected
    >>> await connection.disconnect()   # → revoke + clear local tokens

It also fetches the user profile (display name, avatar) once a token
exists so every surface can show "Connected as <Tochi>" without each
one re-implementing the /me lookup.
"""
from __future__ import annotations

import logging
import time
import webbrowser
from typing import Any

import httpx

from . import oauth

log = logging.getLogger(__name__)


# ── User profile cache ──────────────────────────────────────────────────
#
# /v1/me responses are stable until the user changes their Spotify
# display name or avatar — caching for 5 min avoids hammering Spotify
# every time a UI surface re-renders.
_profile_cache: dict[str, tuple[dict[str, Any], float]] = {}
_PROFILE_TTL_SEC = 300


async def fetch_profile(force: bool = False) -> dict[str, Any] | None:
    """Return ``{display_name, email, avatar_url, product, country, id}``.

    Returns None if not authorized OR if the call fails. Cached for
    5 min per active profile so UI re-renders are cheap.
    """
    p = oauth._profile_name()
    if not force and p in _profile_cache:
        data, ts = _profile_cache[p]
        if time.time() - ts < _PROFILE_TTL_SEC:
            return data

    token = await oauth.get_valid_access_token()
    if not token:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        log.warning("spotify: /me network error: %s", exc)
        return None

    if r.status_code != 200:
        log.warning("spotify: /me http %s", r.status_code)
        return None

    me = r.json()
    images = me.get("images") or []
    profile = {
        "id":           me.get("id", ""),
        "display_name": me.get("display_name") or me.get("id", ""),
        "email":        me.get("email", ""),
        "country":      me.get("country", ""),
        "product":      me.get("product", "free"),     # "premium" / "free" / "open"
        "avatar_url":   images[0]["url"] if images else "",
    }
    _profile_cache[p] = (profile, time.time())
    return profile


def invalidate_profile() -> None:
    """Drop the cached /me profile — call after disconnect or on
    obvious profile changes."""
    _profile_cache.clear()


# ── Connection state ────────────────────────────────────────────────────

def status() -> dict[str, Any]:
    """Snapshot of connection state — safe to surface to any UI.

    Combines the raw auth_status (token presence + expiry) with the
    cached display profile so a single call gives a UI everything it
    needs to render the "Connected as Tochi · Premium" row.
    """
    base = oauth.auth_status()
    p = oauth._profile_name()
    cached = _profile_cache.get(p)
    if cached and base["authorized"]:
        prof, _ = cached
        base["display_name"] = prof.get("display_name", "")
        base["avatar_url"]   = prof.get("avatar_url", "")
        base["product"]      = prof.get("product", "")
        base["needs_premium"] = prof.get("product") != "premium"
    return base


# ── Connect / disconnect ────────────────────────────────────────────────

def start_connect(open_browser: bool = True) -> dict[str, Any]:
    """Kick off the auth flow.

    Returns ``{auth_url, opened, client_id_set}``. When
    ``open_browser=True`` (the default), tries to open the URL in the
    user's default browser. Returns the URL either way so callers can
    show a copy-paste fallback when ``opened=False``.

    The actual token exchange happens later, when Spotify redirects
    back to /auth/spotify/callback.
    """
    if not oauth.CLIENT_ID:
        return {
            "auth_url": "",
            "opened": False,
            "client_id_set": False,
            "error": "no_client_id",
            "message": (
                "Spotify CLIENT_ID isn't configured. Either paste it into "
                "chika/skills/spotify_skill/oauth.py::_DEFAULT_CLIENT_ID "
                "or set CHIKA_SPOTIFY_CLIENT_ID in your environment."
            ),
        }

    url, _state, _verifier = oauth.build_auth_url()
    opened = False
    if open_browser:
        try:
            opened = webbrowser.open(url, new=2, autoraise=True)
        except Exception as exc:
            log.warning("spotify: webbrowser.open failed: %s", exc)

    return {
        "auth_url":      url,
        "opened":        opened,
        "client_id_set": True,
    }


async def disconnect() -> dict[str, Any]:
    """Clear local tokens for the active profile.

    Spotify's API has no programmatic "revoke this app's access"
    endpoint for client-credentials flows — the user has to do that
    at https://www.spotify.com/account/apps/ if they want to nuke
    the grant entirely. We surface that link in the response so the
    UI can offer it.
    """
    oauth.clear_tokens()
    invalidate_profile()
    return {
        "ok":           True,
        "tokens_clear": True,
        "revoke_url":   "https://www.spotify.com/account/apps/",
        "message":      "Disconnected. To fully revoke Chika's access, visit your Spotify account apps page.",
    }
