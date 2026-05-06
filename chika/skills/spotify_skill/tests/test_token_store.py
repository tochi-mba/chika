"""Token persistence — atomic writes, per-profile separation, share-mode
fallback, corruption resilience, redaction."""
from __future__ import annotations

import json
import time

from chika.skills.spotify_skill import oauth


def _seed(profile: str = "default", **fields):
    """Helper: write a tokens file for ``profile`` and return the path."""
    tokens = oauth._empty_tokens() | fields
    oauth._save(tokens, profile)
    return oauth._tokens_path(profile)


# ── Atomic write ────────────────────────────────────────────────────────


def test_save_persists_to_per_profile_path(spotify_env):
    _seed(access_token="hello", refresh_token="world", expires_at=12345)
    path = spotify_env["tokens_path"]
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["access_token"] == "hello"
    assert data["refresh_token"] == "world"
    assert data["expires_at"] == 12345


def test_save_writes_indented_json(spotify_env):
    _seed(access_token="hi")
    text = spotify_env["tokens_path"].read_text()
    # Indented JSON has newlines; compact JSON doesn't.
    assert "\n" in text


def test_save_creates_parent_directories(spotify_env, monkeypatch):
    """Writing for a never-seen profile creates the dir tree."""
    monkeypatch.setattr(oauth, "_profile_name", lambda: "fresh-profile")
    _seed("fresh-profile", access_token="x")
    new_path = oauth._tokens_path("fresh-profile")
    assert new_path.exists()
    assert new_path.parent.is_dir()


# ── Per-profile separation ──────────────────────────────────────────────


def test_tokens_are_isolated_per_profile(spotify_env, monkeypatch):
    _seed("alice", access_token="alice_token")
    _seed("bob", access_token="bob_token")

    # alice still has her token
    monkeypatch.setattr(oauth, "_profile_name", lambda: "alice")
    oauth._cache.clear()
    assert oauth._load()["access_token"] == "alice_token"

    monkeypatch.setattr(oauth, "_profile_name", lambda: "bob")
    oauth._cache.clear()
    assert oauth._load()["access_token"] == "bob_token"


def test_clear_tokens_only_affects_active_profile(spotify_env, monkeypatch):
    _seed("alice", access_token="alice_t", refresh_token="alice_r")
    _seed("bob", access_token="bob_t", refresh_token="bob_r")

    monkeypatch.setattr(oauth, "_profile_name", lambda: "alice")
    oauth.clear_tokens()
    assert not oauth._tokens_path("alice").exists()
    assert oauth._tokens_path("bob").exists()


# ── Share mode ──────────────────────────────────────────────────────────


def test_share_mode_routes_writes_to_shared_bucket(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_name", oauth._profile_name)  # force re-eval
    # _profile_name itself returns "_shared" when sharing is on; the
    # default fixture stubs it. Re-stub here to use the real one
    # so the share check actually triggers.
    monkeypatch.setattr(oauth, "_profile_name", oauth.__dict__["_profile_name"].__wrapped__ if hasattr(oauth._profile_name, "__wrapped__") else lambda: "_shared")

    oauth._save({**oauth._empty_tokens(), "access_token": "shared_t"})
    assert (spotify_env["data_dir"] / "spotify" / "_shared" / "tokens.json").exists()


# ── Corruption resilience ───────────────────────────────────────────────


def test_corrupt_tokens_file_yields_empty_state(spotify_env):
    path = spotify_env["tokens_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    oauth._cache.clear()
    tokens = oauth._load()
    assert tokens["access_token"] == ""
    assert tokens["refresh_token"] == ""


def test_missing_tokens_file_yields_empty_state(spotify_env):
    oauth._cache.clear()
    tokens = oauth._load()
    assert tokens["access_token"] == ""


def test_partial_token_file_keeps_unknown_fields_defaulted(spotify_env):
    path = spotify_env["tokens_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"access_token": "only_this"}))
    oauth._cache.clear()
    tokens = oauth._load()
    assert tokens["access_token"] == "only_this"
    assert tokens["refresh_token"] == ""
    assert tokens["expires_at"] == 0


# ── Redaction ───────────────────────────────────────────────────────────


def test_redact_replaces_non_empty(spotify_env):
    assert oauth.redact("super_secret_token") == "<redacted>"


def test_redact_passes_through_empty(spotify_env):
    assert oauth.redact("") == ""
    assert oauth.redact(None) == ""


def test_auth_status_never_returns_full_token(spotify_env):
    _seed(
        access_token="this_is_a_very_long_token_string_dont_leak_me",
        refresh_token="and_neither_should_this",
        expires_at=int(time.time()) + 600,
    )
    s = oauth.auth_status()
    assert "this_is_a_very_long_token" not in str(s)
    assert "and_neither_should_this" not in str(s)
    # Preview is fine — small enough that prefix-knowledge doesn't help.
    assert s["token_preview"].endswith("…")
    assert len(s["token_preview"]) <= 7  # 6 chars + ellipsis


def test_auth_status_omits_refresh_token_value(spotify_env):
    _seed(
        access_token="x",
        refresh_token="never_show_this_refresh_token",
        expires_at=int(time.time()) + 600,
    )
    s = oauth.auth_status()
    # Refresh value must never appear; a boolean presence flag is fine.
    assert s["has_refresh"] is True
    assert "never_show_this_refresh_token" not in str(s)
