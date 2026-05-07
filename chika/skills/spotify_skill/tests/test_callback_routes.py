"""HTTP route tests for /api/spotify/* and /auth/spotify/callback.

Uses FastAPI's TestClient so we exercise the full request → response
path including JSON serialization and HTML responses. Each test wires
the skill state via fixtures rather than through monkeypatching the
route module directly — closer to how production runs.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chika.skills.spotify_skill import connection, oauth
from chika.skills.spotify_skill.routes import router as spotify_router


@pytest.fixture
def client(spotify_env, monkeypatch) -> TestClient:
    # Stub out the broadcast helper so route tests don't need the
    # live WS infrastructure to be healthy.
    monkeypatch.setattr(
        "chika.skills.spotify_skill.routes.push_to_all_frontend_sessions",
        AsyncMock(),
    )
    app = FastAPI()
    app.include_router(spotify_router)
    return TestClient(app)


# ── /api/spotify/status ────────────────────────────────────────────────


def test_status_when_disconnected(client):
    res = client.get("/api/spotify/status")
    assert res.status_code == 200
    data = res.json()
    assert data["authorized"] is False
    assert data["client_id_set"] is True


def test_status_includes_share_flag(client):
    res = client.get("/api/spotify/status")
    assert "shared" in res.json()


def test_status_does_not_leak_token(client, spotify_env):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "long_token_value_should_not_appear_in_response",
        "refresh_token": "rt",
        "expires_at":   int(time.time()) + 3600,
    })
    res = client.get("/api/spotify/status")
    assert "long_token_value_should_not_appear_in_response" not in res.text


# ── /api/spotify/connect ───────────────────────────────────────────────


def test_connect_returns_url_when_browser_disabled(client, monkeypatch):
    monkeypatch.setattr(connection.webbrowser, "open", MagicMock(return_value=False))
    res = client.post("/api/spotify/connect", params={"open_browser": False})
    data = res.json()
    assert res.status_code == 200
    assert data["auth_url"].startswith("https://accounts.spotify.com/authorize?")
    assert data["client_id_set"] is True


def test_connect_when_client_id_missing(client, monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    res = client.post("/api/spotify/connect")
    data = res.json()
    assert data["error"] == "no_client_id"


# ── /api/spotify/disconnect ────────────────────────────────────────────


def test_disconnect_clears_tokens_and_broadcasts(client, monkeypatch, spotify_env):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    broadcast = AsyncMock()
    monkeypatch.setattr("chika.skills.spotify_skill.routes.push_to_all_frontend_sessions", broadcast)

    res = client.post("/api/spotify/disconnect")
    data = res.json()
    assert data["ok"] is True
    assert oauth.auth_status()["authorized"] is False

    broadcast.assert_awaited_once()
    payload = broadcast.await_args.args[0]
    assert payload["type"] == "spotify_auth_changed"
    assert payload["authorized"] is False


# ── /api/spotify/profile ───────────────────────────────────────────────


def test_profile_unauthorized_returns_401(client):
    res = client.get("/api/spotify/profile")
    assert res.status_code == 401
    assert res.json()["error"] == "not_authorized"


# ── /auth/spotify/callback ─────────────────────────────────────────────


def test_callback_with_error_param_renders_error_page(client):
    res = client.get("/auth/spotify/callback", params={"error": "access_denied"})
    assert res.status_code == 200
    assert "Connection cancelled" in res.text
    assert "access_denied" in res.text


def test_callback_without_code_renders_helpful_error(client):
    res = client.get("/auth/spotify/callback")
    assert res.status_code == 200
    assert "Missing authorization code" in res.text
    assert "redirect URI" in res.text


def test_callback_with_unknown_state_returns_friendly_error(client):
    # Unknown state means the CSRF guard rejected — render a friendly
    # page, not a stack trace.
    res = client.get("/auth/spotify/callback", params={
        "code": "any_code",
        "state": "never_issued_state",
    })
    assert res.status_code == 200
    assert "Token exchange failed" in res.text
    assert "expired or unknown" in res.text


def test_callback_html_includes_trefoil_brand_mark(client):
    res = client.get("/auth/spotify/callback", params={"error": "access_denied"})
    # The branding helper inlines the canonical trefoil SVG; the
    # callback page should include the petal path. (We don't pin
    # exact bytes — that's check_brand_parity.py's job.)
    assert "<svg" in res.text


def test_callback_error_page_escapes_user_input(client):
    """Spotify-supplied error string is HTML-escaped so it can't break
    out of the template."""
    res = client.get("/auth/spotify/callback", params={
        "error": "<script>alert(1)</script>",
    })
    assert "<script>alert(1)</script>" not in res.text
    assert "&lt;script&gt;" in res.text


def test_callback_html_auto_closes_tab(client, monkeypatch, spotify_env):
    """Successful callback sets a window.close() timeout — not testable
    end-to-end here, but we can pin the script presence."""
    # Fake a successful exchange + profile lookup
    from unittest.mock import patch

    async def _fake_exchange(code, state):
        return {"ok": True, "scope": "user-read-private"}

    async def _fake_fetch(force=False):
        return {"display_name": "Tochi", "product": "premium"}

    with patch.object(oauth, "exchange_code", _fake_exchange), \
         patch.object(connection, "fetch_profile", _fake_fetch):
        res = client.get("/auth/spotify/callback", params={
            "code": "x", "state": "y",
        })
    assert "window.close()" in res.text
    assert "Tochi" in res.text


# ── /auth/spotify (legacy redirect) ────────────────────────────────────


def test_auth_spotify_redirects_to_authorize(client):
    res = client.get("/auth/spotify", follow_redirects=False)
    assert res.status_code in (302, 307)
    loc = res.headers["location"]
    assert loc.startswith("https://accounts.spotify.com/authorize?")
    assert "client_id=test_client_id_abc" in loc


def test_auth_spotify_404_when_client_id_missing(client, monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    res = client.get("/auth/spotify", follow_redirects=False)
    assert res.status_code == 400
    assert "isn't configured" in res.text or "not configured" in res.text.lower()
