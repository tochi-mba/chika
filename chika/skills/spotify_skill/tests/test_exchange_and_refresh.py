"""HTTP exchange + refresh paths — happy, failure, and concurrency.

We mock out httpx.AsyncClient so tests never hit Spotify's real
endpoints. Each case asserts on both the on-disk persistence and the
return-value contract.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from chika.skills.spotify_skill import oauth


def _mock_response(status: int, payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload)
    resp.text = str(payload)
    return resp


def _patch_httpx_post(monkeypatch, response: MagicMock) -> AsyncMock:
    """Replace httpx.AsyncClient.post with a one-shot mock returning ``response``."""
    post_mock = AsyncMock(return_value=response)
    client_mock = MagicMock()
    client_mock.post = post_mock
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__  = AsyncMock(return_value=False)
    monkeypatch.setattr(oauth.httpx, "AsyncClient", lambda *a, **k: client_mock)
    return post_mock


# ── Exchange code happy path ────────────────────────────────────────────


def test_exchange_code_persists_tokens(spotify_env, monkeypatch):
    _patch_httpx_post(monkeypatch, _mock_response(200, {
        "access_token":  "fresh_at",
        "refresh_token": "fresh_rt",
        "expires_in":    3600,
        "scope":         "user-read-private streaming",
    }))
    url, state, _ = oauth.build_auth_url()
    assert state in oauth._pkce_state

    result = asyncio.run(oauth.exchange_code("auth_code_xyz", state))
    assert result == {"ok": True, "scope": "user-read-private streaming"}

    # State entry consumed (one-shot)
    assert state not in oauth._pkce_state

    # Persisted to disk
    tokens = oauth._load()
    assert tokens["access_token"] == "fresh_at"
    assert tokens["refresh_token"] == "fresh_rt"
    assert tokens["expires_at"] > time.time() + 3500


def test_exchange_code_with_unknown_state_returns_error(spotify_env, monkeypatch):
    # Even if Spotify would accept the code, an unknown state aborts
    # the exchange — the CSRF guard.
    post = _patch_httpx_post(monkeypatch, _mock_response(200, {"access_token": "x"}))
    result = asyncio.run(oauth.exchange_code("code", "this_state_was_never_issued"))
    assert result["error"] == "unknown_state"
    # Importantly, no HTTP call was made — we rejected before contacting Spotify.
    post.assert_not_awaited()


def test_exchange_code_with_4xx_surfaces_error(spotify_env, monkeypatch):
    _patch_httpx_post(monkeypatch, _mock_response(400, {
        "error": "invalid_grant",
        "error_description": "Invalid authorization code",
    }))
    _, state, _ = oauth.build_auth_url()
    result = asyncio.run(oauth.exchange_code("bad_code", state))
    assert result["error"] == "invalid_grant"
    assert "Invalid authorization code" in result["message"]


def test_exchange_code_handles_network_failure(spotify_env, monkeypatch):
    """An httpx network error returns a structured error, doesn't raise."""
    client_mock = MagicMock()
    client_mock.post = AsyncMock(side_effect=oauth.httpx.HTTPError("connection reset"))
    client_mock.__aenter__ = AsyncMock(return_value=client_mock)
    client_mock.__aexit__  = AsyncMock(return_value=False)
    monkeypatch.setattr(oauth.httpx, "AsyncClient", lambda *a, **k: client_mock)

    _, state, _ = oauth.build_auth_url()
    result = asyncio.run(oauth.exchange_code("code", state))
    assert result["error"] == "network"


def test_exchange_code_persists_only_on_success(spotify_env, monkeypatch):
    _patch_httpx_post(monkeypatch, _mock_response(400, {"error": "invalid_grant"}))
    _, state, _ = oauth.build_auth_url()
    asyncio.run(oauth.exchange_code("bad_code", state))
    assert not spotify_env["tokens_path"].exists()


# ── Refresh path ────────────────────────────────────────────────────────


def test_refresh_uses_stored_refresh_token(spotify_env, monkeypatch):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token":  "expired_at",
        "refresh_token": "rt_xyz",
        "expires_at":    int(time.time()) - 1,  # already expired
    })
    post = _patch_httpx_post(monkeypatch, _mock_response(200, {
        "access_token": "new_at",
        "expires_in":   3600,
    }))

    new_at = asyncio.run(oauth.refresh_access_token())
    assert new_at == "new_at"
    # The request body included grant_type=refresh_token + the stored RT.
    args, kwargs = post.call_args
    assert "grant_type=refresh_token" in str(kwargs.get("data") or args[1] if len(args) > 1 else "") or kwargs["data"]["grant_type"] == "refresh_token"
    assert kwargs["data"]["refresh_token"] == "rt_xyz"


def test_refresh_with_no_refresh_token_returns_empty(spotify_env, monkeypatch):
    # No stored refresh token — refresh must short-circuit without
    # making an HTTP call.
    post = _patch_httpx_post(monkeypatch, _mock_response(200, {"access_token": "x"}))
    result = asyncio.run(oauth.refresh_access_token())
    assert result == ""
    post.assert_not_awaited()


def test_refresh_invalid_grant_clears_stored_refresh_token(spotify_env, monkeypatch):
    """When Spotify says the refresh token is no longer valid (user
    changed password / revoked access), we wipe it so the next call
    surfaces ``needs_reauth`` cleanly instead of looping on a dead RT."""
    oauth._save({
        **oauth._empty_tokens(),
        "access_token":  "stale",
        "refresh_token": "revoked_rt",
        "expires_at":    int(time.time()) - 60,
    })
    _patch_httpx_post(monkeypatch, _mock_response(400, {"error": "invalid_grant"}))

    asyncio.run(oauth.refresh_access_token())
    tokens = oauth._load()
    assert tokens["refresh_token"] == ""
    assert tokens["access_token"] == ""


def test_refresh_rotates_refresh_token_when_returned(spotify_env, monkeypatch):
    oauth._save({
        **oauth._empty_tokens(),
        "refresh_token": "old_rt",
        "expires_at":    int(time.time()) - 1,
    })
    _patch_httpx_post(monkeypatch, _mock_response(200, {
        "access_token":  "new_at",
        "refresh_token": "rotated_rt",
        "expires_in":    3600,
    }))
    asyncio.run(oauth.refresh_access_token())
    assert oauth._load()["refresh_token"] == "rotated_rt"


def test_refresh_keeps_old_rt_when_not_returned(spotify_env, monkeypatch):
    """Spotify often omits the refresh_token from the response — that
    means "keep using the existing one"."""
    oauth._save({
        **oauth._empty_tokens(),
        "refresh_token": "kept_rt",
        "expires_at":    int(time.time()) - 1,
    })
    _patch_httpx_post(monkeypatch, _mock_response(200, {
        "access_token": "new_at",
        "expires_in":   3600,
    }))
    asyncio.run(oauth.refresh_access_token())
    assert oauth._load()["refresh_token"] == "kept_rt"


# ── Concurrent refresh ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_refresh_calls_share_one_http_request(spotify_env, monkeypatch):
    """Two simultaneous refresh attempts coalesce — only one HTTP
    request is fired. The second waits on the lock, then sees the
    refreshed token in cache and returns it without re-firing."""
    oauth._save({
        **oauth._empty_tokens(),
        "refresh_token": "rt",
        "expires_at":    int(time.time()) - 60,
    })
    post = _patch_httpx_post(monkeypatch, _mock_response(200, {
        "access_token": "shared_at",
        "expires_in":   3600,
    }))

    results = await asyncio.gather(
        oauth.refresh_access_token(),
        oauth.refresh_access_token(),
        oauth.refresh_access_token(),
    )
    assert all(r == "shared_at" for r in results)
    # Only one of the three actually went over the wire.
    assert post.await_count == 1


# ── get_valid_access_token ──────────────────────────────────────────────


def test_get_valid_returns_existing_token_when_fresh(spotify_env):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "still_good",
        "refresh_token": "rt",
        "expires_at":   int(time.time()) + 600,
    })
    assert asyncio.run(oauth.get_valid_access_token()) == "still_good"


def test_get_valid_refreshes_when_expired(spotify_env, monkeypatch):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "expired",
        "refresh_token": "rt",
        "expires_at":    int(time.time()) - 1,
    })
    _patch_httpx_post(monkeypatch, _mock_response(200, {
        "access_token": "fresh",
        "expires_in":   3600,
    }))
    assert asyncio.run(oauth.get_valid_access_token()) == "fresh"


def test_get_valid_returns_empty_when_nothing_stored(spotify_env):
    assert asyncio.run(oauth.get_valid_access_token()) == ""
