"""PKCE primitive tests — verifier generation, challenge derivation,
state bookkeeping, TTL pruning, CSRF protection."""
from __future__ import annotations

import base64
import hashlib

import pytest

from chika.skills.spotify_skill import oauth


def test_code_verifier_is_url_safe_and_long_enough(spotify_env):
    v = oauth._gen_code_verifier()
    # RFC 7636: verifier ≥ 43, ≤ 128 chars, [A-Z a-z 0-9 - . _ ~]
    assert 43 <= len(v) <= 128
    assert all(c.isalnum() or c in "-._~" for c in v)


def test_code_challenge_matches_sha256_of_verifier(spotify_env):
    v = "abc123" * 8
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert oauth._gen_code_challenge(v) == expected


def test_two_verifiers_collide_with_negligible_probability(spotify_env):
    """Generates 1k verifiers and asserts they're all distinct."""
    seen = {oauth._gen_code_verifier() for _ in range(1000)}
    assert len(seen) == 1000


def test_build_auth_url_includes_required_params(spotify_env):
    url, state, verifier = oauth.build_auth_url()
    assert url.startswith("https://accounts.spotify.com/authorize?")
    for token in (
        "client_id=test_client_id_abc",
        "response_type=code",
        f"state={state}",
        "code_challenge_method=S256",
        "code_challenge=",
    ):
        assert token in url, f"missing {token!r} in {url!r}"
    # verifier is stashed for the callback to retrieve
    assert state in oauth._pkce_state
    assert oauth._pkce_state[state][0] == verifier


def test_build_auth_url_raises_when_client_id_missing(spotify_env, monkeypatch):
    monkeypatch.setattr(oauth, "CLIENT_ID", "")
    with pytest.raises(RuntimeError, match="client_id"):
        oauth.build_auth_url()


def test_pkce_state_pruned_after_ttl(spotify_env, monkeypatch):
    """Stale state entries get pruned; fresh ones don't.

    We patch time.time inside the oauth module specifically so we can
    seed two state entries at distinct timestamps, then advance the
    clock past the TTL of only the first.
    """
    fake_now = [1000.0]
    monkeypatch.setattr(oauth.time, "time", lambda: fake_now[0])

    # First state seeded @ t=1000
    oauth.build_auth_url()
    # Advance enough that the FIRST is now stale, but the SECOND we're
    # about to seed will be fresh.
    fake_now[0] = 1000 + oauth._PKCE_TTL_SEC + 100  # t = TTL + 100
    # Second state seeded "now" — this one is fresh.
    oauth.build_auth_url()

    # Prune happens "now" (same fake clock). The first entry's
    # timestamp (1000) is < cutoff (now − TTL); the second's matches
    # the current clock so it survives.
    oauth._prune_pkce()
    assert len(oauth._pkce_state) == 1


def test_each_call_generates_a_unique_state(spotify_env):
    seen = set()
    for _ in range(50):
        _, state, _ = oauth.build_auth_url()
        assert state not in seen
        seen.add(state)


def test_state_csrf_protection_unknown_state_rejects(spotify_env):
    # If a callback arrives with a state we never issued, exchange_code
    # must refuse (returns error). This is the CSRF defense.
    import asyncio
    result = asyncio.run(oauth.exchange_code("any_code", "never_issued_state"))
    assert "error" in result
    assert result["error"] == "unknown_state"
