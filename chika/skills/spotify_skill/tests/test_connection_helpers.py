"""High-level connection.py tests — start_connect, fetch_profile,
disconnect, status, profile cache TTL."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from chika.skills.spotify_skill import connection, oauth

# ── start_connect ──────────────────────────────────────────────────────


def test_start_connect_returns_url_when_browser_disabled(spotify_env, monkeypatch):
    """open_browser=False → URL only, no webbrowser.open call."""
    open_mock = MagicMock(return_value=True)
    monkeypatch.setattr(connection.webbrowser, "open", open_mock)

    result = connection.start_connect(open_browser=False)
    assert result["client_id_set"] is True
    assert result["auth_url"].startswith("https://accounts.spotify.com/authorize?")
    assert result["opened"] is False
    open_mock.assert_not_called()


def test_start_connect_opens_browser_by_default(spotify_env, monkeypatch):
    open_mock = MagicMock(return_value=True)
    monkeypatch.setattr(connection.webbrowser, "open", open_mock)
    result = connection.start_connect()
    assert result["opened"] is True
    open_mock.assert_called_once()


def test_start_connect_handles_browser_open_failure(spotify_env, monkeypatch):
    """If webbrowser.open raises, we still surface the URL — the user
    can copy-paste it. Never let the UI hang on an unhandled exception."""
    monkeypatch.setattr(connection.webbrowser, "open", MagicMock(side_effect=RuntimeError("no display")))
    result = connection.start_connect()
    assert result["auth_url"]
    assert result["opened"] is False


def test_start_connect_without_client_id_returns_error(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    result = connection.start_connect()
    assert result["error"] == "no_client_id"
    assert result["client_id_set"] is False
    assert "CHIKA_SPOTIFY_CLIENT_ID" in result["message"]


# ── fetch_profile ──────────────────────────────────────────────────────


def _patch_get(monkeypatch, status: int, payload: dict | None = None) -> AsyncMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload or {})
    get_mock = AsyncMock(return_value=resp)
    client_mock = MagicMock()
    client_mock.get = get_mock
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__  = AsyncMock(return_value=False)
    monkeypatch.setattr(connection.httpx, "AsyncClient", lambda *a, **k: client_mock)
    return get_mock


def test_fetch_profile_returns_none_when_unauthorized(spotify_env, monkeypatch):
    # No tokens stored → no access token → fetch returns None without
    # calling Spotify.
    get_mock = _patch_get(monkeypatch, 200, {"id": "x"})
    result = asyncio.run(connection.fetch_profile())
    assert result is None
    get_mock.assert_not_awaited()


def test_fetch_profile_caches_result(spotify_env, monkeypatch):
    """Two fetches inside the TTL share one HTTP call."""
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    get_mock = _patch_get(monkeypatch, 200, {
        "id": "tochi",
        "display_name": "Tochi",
        "product": "premium",
        "images": [{"url": "https://img/avatar.png"}],
    })
    p1 = asyncio.run(connection.fetch_profile())
    p2 = asyncio.run(connection.fetch_profile())
    assert p1 == p2
    assert p1["display_name"] == "Tochi"
    assert p1["product"] == "premium"
    assert p1["avatar_url"] == "https://img/avatar.png"
    assert get_mock.await_count == 1   # cached


def test_fetch_profile_force_refresh_bypasses_cache(spotify_env, monkeypatch):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    get_mock = _patch_get(monkeypatch, 200, {"id": "x", "display_name": "X"})
    asyncio.run(connection.fetch_profile())
    asyncio.run(connection.fetch_profile(force=True))
    assert get_mock.await_count == 2


def test_fetch_profile_tolerates_missing_avatar(spotify_env, monkeypatch):
    """Some Spotify accounts have no avatar at all (empty `images` array
    or missing key). The helper must not KeyError."""
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    _patch_get(monkeypatch, 200, {"id": "x", "display_name": "Avatar-less"})
    result = asyncio.run(connection.fetch_profile(force=True))
    assert result["avatar_url"] == ""


def test_fetch_profile_handles_5xx(spotify_env, monkeypatch):
    """Spotify outage / 503 → return None, don't crash."""
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    _patch_get(monkeypatch, 503)
    result = asyncio.run(connection.fetch_profile(force=True))
    assert result is None


def test_invalidate_profile_drops_cache(spotify_env, monkeypatch):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    _patch_get(monkeypatch, 200, {"id": "x", "display_name": "Y"})
    asyncio.run(connection.fetch_profile())
    connection.invalidate_profile()
    # Empty cache means next fetch hits the wire again — verify by
    # ensuring the cache dict is actually cleared.
    assert connection._profile_cache == {}


# ── status() ────────────────────────────────────────────────────────────


def test_status_when_disconnected(spotify_env):
    s = connection.status()
    assert s["authorized"] is False
    assert s["client_id_set"] is True
    assert s["needs_reauth"] is True


def test_status_when_connected_includes_profile_data(spotify_env):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    # Seed the profile cache directly so status() picks it up
    connection._profile_cache["default"] = (
        {"display_name": "Tochi", "product": "premium", "avatar_url": "x"},
        time.time(),
    )
    s = connection.status()
    assert s["authorized"] is True
    assert s["display_name"] == "Tochi"
    assert s["product"] == "premium"
    assert s["needs_premium"] is False


def test_status_marks_free_tier_as_needs_premium(spotify_env):
    """Most playback control needs Premium — flag for the UI to surface."""
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    connection._profile_cache["default"] = (
        {"display_name": "F", "product": "free", "avatar_url": ""},
        time.time(),
    )
    s = connection.status()
    assert s["needs_premium"] is True


# ── disconnect() ────────────────────────────────────────────────────────


def test_disconnect_clears_tokens(spotify_env):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    result = asyncio.run(connection.disconnect())
    assert result["ok"] is True
    assert result["tokens_clear"] is True
    assert "spotify.com/account/apps" in result["revoke_url"]
    assert oauth.auth_status()["authorized"] is False


def test_disconnect_invalidates_profile_cache(spotify_env):
    connection._profile_cache["default"] = ({"display_name": "x"}, time.time())
    asyncio.run(connection.disconnect())
    assert connection._profile_cache == {}
