"""Skill-local pytest fixtures for the Spotify skill.

Lives next to the skill (per project convention) so the suite is
self-contained: ``pytest chika/skills/spotify_skill/tests`` runs
everything Spotify-specific without pulling the whole top-level
``tests/`` tree.

The big shared fixture here is ``spotify_env`` — it points the OAuth
module at a temp directory for token storage, fakes a CLIENT_ID, and
clears every in-memory cache between tests. Without that, tests would
leak tokens between cases via the module-level ``_cache`` dict.
"""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def spotify_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
    """Isolate OAuth state into ``tmp_path`` and a fake CLIENT_ID.

    Yields a dict with the salient paths so tests can assert on them
    directly instead of recomputing.
    """
    monkeypatch.setenv("CHIKA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHIKA_SPOTIFY_CLIENT_ID", "test_client_id_abc")

    # Re-import to pick up the new env vars at module scope.
    from chika.skills.spotify_skill import connection as _connection
    from chika.skills.spotify_skill import oauth as _oauth

    # The CLIENT_ID lives at module scope; force-refresh it.
    _oauth.CLIENT_ID = os.environ["CHIKA_SPOTIFY_CLIENT_ID"]

    # Wipe any leftovers from earlier tests in this process.
    _oauth._cache.clear()
    _oauth._pkce_state.clear()
    _oauth._refresh_locks.clear()
    _connection._profile_cache.clear()
    # Wipe the disk-side pending-states file too — earlier tests in
    # this process may have written entries that would leak into
    # this one.
    try:
        _oauth._pending_states_path().unlink(missing_ok=True)
    except Exception:
        pass

    # Stub the LEAF resolvers (active profile + share flag + override
    # flag) — leave the top-level _profile_name resolution tree alone
    # so it walks the real branches in tests. Without this, every
    # test that needs to exercise the share/override logic would have
    # to re-stub _profile_name itself.
    monkeypatch.setattr(_oauth, "_active_profile_name", lambda: "default")
    monkeypatch.setattr(_oauth, "_share_across_profiles", lambda: False)
    monkeypatch.setattr(_oauth, "_profile_overrides_share", lambda: False)

    yield {
        "data_dir":     tmp_path,
        "tokens_path":  tmp_path / "spotify" / "default" / "tokens.json",
    }

    _oauth._cache.clear()
    _oauth._pkce_state.clear()
    _oauth._refresh_locks.clear()
    _connection._profile_cache.clear()
