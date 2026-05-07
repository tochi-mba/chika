"""``chika spotify ...`` argv subcommand — usage, status output,
connect happy path, share toggle wiring."""
from __future__ import annotations

import io
import time
from contextlib import redirect_stdout
from unittest.mock import MagicMock

from chika.skills.spotify_skill import cli as spotify_cmd
from chika.skills.spotify_skill import oauth

# ── Argv parsing ────────────────────────────────────────────────────────


def test_no_args_prints_usage(spotify_env):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main([])
    assert rc == 0
    assert "chika spotify" in buf.getvalue()
    assert "connect" in buf.getvalue()


def test_help_flag_prints_usage(spotify_env):
    for flag in ("--help", "-h", "help"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = spotify_cmd.main([flag])
        assert rc == 0
        assert "Commands:" in buf.getvalue()


def test_unknown_subcommand_exits_non_zero(spotify_env):
    rc = spotify_cmd.main(["nope"])
    assert rc == 2


def test_share_without_value_exits_non_zero(spotify_env):
    rc = spotify_cmd.main(["share"])
    assert rc == 2


def test_share_with_invalid_value_exits_non_zero(spotify_env):
    rc = spotify_cmd.main(["share", "maybe"])
    assert rc == 2


# ── Status ──────────────────────────────────────────────────────────────


def test_status_when_disconnected(spotify_env):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["status"])
    assert rc == 0
    assert "not connected" in buf.getvalue().lower()


def test_status_when_no_client_id(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["status"])
    # Returns non-zero so a setup script can branch on it
    assert rc == 1
    assert "isn't configured" in buf.getvalue().lower()


def test_status_when_connected(spotify_env, monkeypatch):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })

    # Stub fetch_profile so we don't hit the network
    async def _fake_fetch(force=False):
        return {"display_name": "Tochi", "product": "premium"}

    monkeypatch.setattr(
        "chika.skills.spotify_skill.connection.fetch_profile",
        _fake_fetch,
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["status"])
    assert rc == 0
    out = buf.getvalue()
    assert "Tochi" in out
    assert "premium" in out


# ── Connect ─────────────────────────────────────────────────────────────


def test_connect_no_open_returns_url(spotify_env, monkeypatch):
    open_mock = MagicMock(return_value=False)
    monkeypatch.setattr(
        "chika.skills.spotify_skill.connection.webbrowser.open",
        open_mock,
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["connect", "--no-open"])
    assert rc == 0
    out = buf.getvalue()
    assert "https://accounts.spotify.com/authorize?" in out
    open_mock.assert_not_called()


def test_connect_opens_browser(spotify_env, monkeypatch):
    open_mock = MagicMock(return_value=True)
    monkeypatch.setattr(
        "chika.skills.spotify_skill.connection.webbrowser.open",
        open_mock,
    )

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["connect"])
    assert rc == 0
    open_mock.assert_called_once()
    out = buf.getvalue()
    assert "Opening Spotify in your browser" in out


def test_connect_fails_cleanly_without_client_id(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["connect"])
    assert rc == 1
    assert "isn't configured" in buf.getvalue() or "not configured" in buf.getvalue().lower()


# ── Disconnect ──────────────────────────────────────────────────────────


def test_disconnect_clears_tokens(spotify_env):
    oauth._save({
        **oauth._empty_tokens(),
        "access_token": "t",
        "refresh_token": "r",
        "expires_at":   int(time.time()) + 3600,
    })
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["disconnect"])
    assert rc == 0
    assert "Disconnected" in buf.getvalue()
    assert oauth.auth_status()["authorized"] is False


# ── Share toggle ────────────────────────────────────────────────────────


def test_share_on_writes_to_settings(spotify_env, monkeypatch, tmp_path):
    from api import settings_store
    monkeypatch.setattr(settings_store, "_SETTINGS_PATH", tmp_path / "settings.json")
    settings_store._settings = {}
    settings_store.init({})

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = spotify_cmd.main(["share", "on"])
    assert rc == 0
    assert settings_store.get("spotify_share_across_profiles") == "on"


def test_share_off_writes_to_settings(spotify_env, monkeypatch, tmp_path):
    from api import settings_store
    monkeypatch.setattr(settings_store, "_SETTINGS_PATH", tmp_path / "settings.json")
    settings_store._settings = {}
    settings_store.init({})

    spotify_cmd.main(["share", "on"])
    spotify_cmd.main(["share", "off"])
    assert settings_store.get("spotify_share_across_profiles") == "off"
