"""Per-profile override of the share-across-profiles flag.

This is the third resolution mode — when global sharing is on, a
specific profile can opt out and use its own Spotify connection.
Tests cover every branch of the resolution tree:

  share off + no override        → per-profile bucket
  share off + override           → per-profile bucket (override redundant)
  share on  + no override        → _shared bucket
  share on  + override           → per-profile bucket
  share on  + override flipped   → bucket changes mid-session

Plus settings_store validation, status reporting, isolation guarantees.
"""
from __future__ import annotations

import pytest

from chika.skills.spotify_skill import oauth

# ── Resolution-tree branches ────────────────────────────────────────────


def test_share_off_no_override_uses_per_profile_bucket(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: False)
    monkeypatch.setattr(oauth, "_profile_overrides_share", lambda: False)
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")

    assert oauth._profile_name() == "alice"


def test_share_off_with_override_still_uses_per_profile_bucket(spotify_env, monkeypatch):
    """Override is redundant when sharing is off — but enabling it
    shouldn't break anything. Profile still reads its own bucket."""
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: False)
    monkeypatch.setattr(oauth, "_profile_overrides_share", lambda: True)
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")
    assert oauth._profile_name() == "alice"


def test_share_on_no_override_uses_shared_bucket(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_overrides_share", lambda: False)
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")
    assert oauth._profile_name() == "_shared"


def test_share_on_with_override_uses_per_profile_bucket(spotify_env, monkeypatch):
    """The killer case: global sharing is on, but THIS profile opts
    out and uses its own connection."""
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_overrides_share", lambda: True)
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")
    assert oauth._profile_name() == "alice"


# ── Token isolation under override ──────────────────────────────────────


def test_override_profile_does_not_pollute_shared_bucket(spotify_env, monkeypatch):
    """Profile alice has override on; her tokens save to ``alice/``,
    not ``_shared/``. Profile bob (no override) reads ``_shared/`` and
    sees an empty bucket."""
    # Set up: share on, alice overrides, bob doesn't.
    overrides = {"alice": True}

    def share_on(): return True
    def alice_override(): return overrides.get("alice", False)
    def bob_override():   return overrides.get("bob", False)

    monkeypatch.setattr(oauth, "_share_across_profiles", share_on)

    # Save under alice (override on)
    monkeypatch.setattr(oauth, "_profile_overrides_share", alice_override)
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")
    oauth._save({**oauth._empty_tokens(), "access_token": "alice_private"})

    # bob should see an empty _shared bucket
    monkeypatch.setattr(oauth, "_profile_overrides_share", bob_override)
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "bob")
    oauth._cache.clear()
    assert oauth._load()["access_token"] == ""

    # alice's tokens are isolated to her bucket
    monkeypatch.setattr(oauth, "_profile_overrides_share", alice_override)
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")
    oauth._cache.clear()
    assert oauth._load()["access_token"] == "alice_private"


def test_override_lets_two_profiles_use_different_accounts_under_share(spotify_env, monkeypatch):
    """The user-facing promise: with sharing on AND alice overriding,
    alice can connect a separate Spotify account from the shared one."""
    overrides = {"alice": True}
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_overrides_share",
                        lambda: overrides.get(oauth._active_profile_name(), False))

    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "default")
    oauth._save({**oauth._empty_tokens(), "access_token": "shared_team_account"})

    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")
    oauth._cache.clear()
    oauth._save({**oauth._empty_tokens(), "access_token": "alice_personal"})

    # Re-read from each profile context
    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "default")
    oauth._cache.clear()
    assert oauth._load()["access_token"] == "shared_team_account"

    monkeypatch.setattr(oauth, "_active_profile_name", lambda: "alice")
    oauth._cache.clear()
    assert oauth._load()["access_token"] == "alice_personal"


# ── Settings store validation ───────────────────────────────────────────


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    from api import settings_store
    monkeypatch.setattr(settings_store, "_SETTINGS_PATH", tmp_path / "settings.json")
    settings_store._settings = {}
    settings_store.init({})
    return settings_store


def test_settings_accepts_valid_overrides(isolated_settings):
    isolated_settings.update({
        "spotify_profile_overrides": {"alice": True, "bob": False, "carol": True},
    })
    # False entries are dropped from the persisted dict (keeps it tidy)
    saved = isolated_settings.get("spotify_profile_overrides")
    assert saved == {"alice": True, "carol": True}


def test_settings_clears_overrides_when_empty(isolated_settings):
    isolated_settings.update({"spotify_profile_overrides": {"alice": True}})
    isolated_settings.update({"spotify_profile_overrides": {}})
    assert isolated_settings.get("spotify_profile_overrides") == {}


def test_settings_clears_overrides_on_none(isolated_settings):
    isolated_settings.update({"spotify_profile_overrides": {"alice": True}})
    isolated_settings.update({"spotify_profile_overrides": None})
    assert isolated_settings.get("spotify_profile_overrides") == {}


def test_settings_rejects_non_dict_overrides(isolated_settings):
    with pytest.raises(ValueError, match="dict"):
        isolated_settings.update({"spotify_profile_overrides": "alice"})


def test_settings_rejects_non_bool_override_value(isolated_settings):
    with pytest.raises(ValueError, match="bool"):
        isolated_settings.update({
            "spotify_profile_overrides": {"alice": "yes"},
        })


def test_settings_rejects_non_string_profile_name(isolated_settings):
    with pytest.raises(ValueError, match="str"):
        isolated_settings.update({
            "spotify_profile_overrides": {123: True},
        })


def test_changing_override_invalidates_token_cache(isolated_settings, spotify_env, monkeypatch):
    """Toggling override must wipe the in-memory cache so the next
    read picks up the right bucket."""
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    oauth._save({**oauth._empty_tokens(), "access_token": "stale"})
    oauth._load()  # priming
    isolated_settings.update({"spotify_profile_overrides": {"default": True}})
    assert oauth._cache == {}


# ── auth_status surface ─────────────────────────────────────────────────


def test_auth_status_reports_override_state(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_overrides_share", lambda: True)
    s = oauth.auth_status()
    assert s["shared_setting"] is True
    assert s["overrides_share"] is True
    # ``shared`` is the *effective* state — overridden profile is NOT shared
    assert s["shared"] is False


def test_auth_status_reports_shared_when_no_override(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: True)
    monkeypatch.setattr(oauth, "_profile_overrides_share", lambda: False)
    s = oauth.auth_status()
    assert s["shared"] is True
    assert s["shared_setting"] is True
    assert s["overrides_share"] is False


def test_auth_status_off_when_share_off_regardless_of_override(spotify_env, monkeypatch):
    """When global sharing is off, the override is moot — both flags
    should reflect that."""
    monkeypatch.setattr(oauth, "_share_across_profiles", lambda: False)
    monkeypatch.setattr(oauth, "_profile_overrides_share", lambda: True)
    s = oauth.auth_status()
    assert s["shared"] is False
    assert s["shared_setting"] is False
    # We surface the raw override flag too, even when it has no effect,
    # so the UI knows to keep the toggle in its checked-but-greyed state.
    assert s["overrides_share"] is True
