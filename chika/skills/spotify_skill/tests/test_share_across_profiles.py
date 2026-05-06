"""Share-across-profiles toggle — bucket switching, isolation when off,
shared bucket when on, integration with settings_store.update."""
from __future__ import annotations

import time

import pytest

from chika.skills.spotify_skill import oauth


def test_default_is_per_profile_isolation(spotify_env, monkeypatch):
    """Out of the box, every profile has its own token bucket."""
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: False)
    monkeypatch.setattr(oauth, "_profile_name", lambda: "alice")
    oauth._save({**oauth._empty_tokens(), "access_token": "alice_t"})

    monkeypatch.setattr(oauth, "_profile_name", lambda: "bob")
    oauth._cache.clear()
    assert oauth._load()["access_token"] == ""  # bob is fresh


def test_share_mode_collapses_buckets(spotify_env, monkeypatch):
    """When sharing is on, every profile reads the ``_shared`` bucket."""
    # First, save under shared bucket
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_name", lambda: "_shared")
    oauth._save({**oauth._empty_tokens(), "access_token": "shared_t"})

    # Now any profile name should resolve to "_shared" and pick it up.
    # In practice the resolver itself returns "_shared" — test that
    # path via the real function:
    from chika.skills.spotify_skill.oauth import _profile_name as real_resolver
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_name", real_resolver)

    oauth._cache.clear()
    assert oauth._load()["access_token"] == "shared_t"


def test_toggle_share_via_settings_clears_token_cache(spotify_env, monkeypatch, tmp_path):
    """Flipping the setting must invalidate the in-memory cache so the
    next read picks up the right bucket. Without this, a user who
    just toggled on/off would see stale state until process restart."""
    from api import settings_store

    # Point settings_store at a temp file
    monkeypatch.setattr(settings_store, "_SETTINGS_PATH", tmp_path / "settings.json")
    settings_store._settings = {}
    settings_store.init({})

    # Seed a per-profile token, then prime the cache
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: False)
    monkeypatch.setattr(oauth, "_profile_name", lambda: "default")
    oauth._save({**oauth._empty_tokens(), "access_token": "per_profile_t"})
    oauth._load()  # priming

    # Flip the share flag — settings_store.update must wipe the cache
    settings_store.update({"spotify_share_across_profiles": "on"})
    assert oauth._cache == {}


def test_share_mode_status_reports_shared_true(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    s = oauth.auth_status()
    assert s["shared"] is True


def test_per_profile_mode_status_reports_shared_false(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: False)
    s = oauth.auth_status()
    assert s["shared"] is False


def test_invalid_share_value_rejected_by_settings_store(spotify_env, monkeypatch, tmp_path):
    from api import settings_store
    monkeypatch.setattr(settings_store, "_SETTINGS_PATH", tmp_path / "settings.json")
    settings_store._settings = {}
    settings_store.init({})
    with pytest.raises(ValueError, match="spotify_share_across_profiles"):
        settings_store.update({"spotify_share_across_profiles": "maybe"})


def test_share_mode_lets_two_profiles_share_one_token(spotify_env, monkeypatch):
    """The actual user-facing promise: with sharing on, profile A
    reads the same token profile B saved."""
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)

    from chika.skills.spotify_skill.oauth import _profile_name as real_resolver
    monkeypatch.setattr(oauth, "_profile_name", real_resolver)

    # Profile A saves
    oauth._save({**oauth._empty_tokens(), "access_token": "shared_zzz", "expires_at": int(time.time()) + 3600})
    oauth._cache.clear()  # simulate process boundary

    # Profile B (any name — resolves to "_shared") reads
    assert oauth._load()["access_token"] == "shared_zzz"
