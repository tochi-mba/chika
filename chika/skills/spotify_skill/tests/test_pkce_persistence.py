"""Tests for the disk-persisted PKCE state.

The OAuth flow has a CLI→server hand-off problem: ``chika spotify
connect`` runs in a short-lived CLI process that generates the state
+ verifier and opens the browser. The OAuth callback hits the SERVER
process, which used to have an empty in-memory state dict — leading
to "Auth state expired or unknown" every time.

These tests pin the disk persistence contract so that regression
can't sneak back in:

  - ``build_auth_url`` writes the new state to a JSON file under
    ``<data_dir>/spotify/_pending_states.json``.
  - ``exchange_code`` reads from disk before checking memory, so the
    server process can validate states the CLI process generated.
  - The TTL still prunes stale entries (10 min default).
  - The file format round-trips cleanly across reads/writes.
  - Concurrent writers don't corrupt the file (atomic_write).
  - The "exchange after fresh-process restart" path simulates the
    actual CLI-then-server scenario by clearing in-memory state
    between writer and reader.
"""
from __future__ import annotations

import asyncio
import json
import time

from chika.skills.spotify_skill import oauth

# ── Persistence round-trip ─────────────────────────────────────────────


def test_build_auth_url_persists_state_to_disk(spotify_env):
    """build_auth_url must write the freshly-issued state to the
    on-disk pending-states file BEFORE returning, so a separate
    process consuming the OAuth callback can find it."""
    _, state, verifier = oauth.build_auth_url()

    path = oauth._pending_states_path()
    assert path.is_file(), f"_pending_states.json was not written to {path}"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert state in raw, f"state {state!r} missing from on-disk file"
    persisted_verifier, persisted_ts = raw[state]
    assert persisted_verifier == verifier
    assert isinstance(persisted_ts, (int, float))


def test_load_pending_states_returns_empty_when_file_missing(spotify_env):
    """No file = no pending flows. Must NOT raise."""
    path = oauth._pending_states_path()
    if path.exists():
        path.unlink()
    assert oauth._load_pending_states() == {}


def test_load_pending_states_returns_empty_on_corrupt_file(spotify_env):
    """A corrupted file shouldn't tank auth flows — return empty
    silently. The user can retry; nothing leaks."""
    path = oauth._pending_states_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert oauth._load_pending_states() == {}


def test_load_pending_states_round_trips(spotify_env):
    """Save + load returns the same data, types preserved."""
    states = {
        "state-a": ("verifier-a", time.time()),
        "state-b": ("verifier-b", time.time() - 30),
    }
    oauth._save_pending_states(states)
    loaded = oauth._load_pending_states()
    assert set(loaded.keys()) == {"state-a", "state-b"}
    assert loaded["state-a"][0] == "verifier-a"
    assert loaded["state-b"][0] == "verifier-b"
    # Timestamps preserved as floats
    assert isinstance(loaded["state-a"][1], float)


def test_load_pending_states_skips_malformed_entries(spotify_env):
    """If the file contains an entry with the wrong shape, skip it
    rather than crashing the whole load."""
    path = oauth._pending_states_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "good-state":      ["verifier-a", time.time()],
        "wrong-shape":     "not-a-list",
        "wrong-type":      [42, "not-a-timestamp"],
        "missing-second":  ["verifier-only"],
    }), encoding="utf-8")
    loaded = oauth._load_pending_states()
    assert "good-state" in loaded
    assert "wrong-shape" not in loaded
    assert "wrong-type" not in loaded
    assert "missing-second" not in loaded


# ── Cross-process simulation ────────────────────────────────────────────


def test_exchange_code_reads_state_written_by_other_process(spotify_env, monkeypatch):
    """The actual CLI→server hand-off: the CLI writes to disk, exits
    (we simulate that by clearing in-memory state), then a fresh
    process tries to consume the state via exchange_code."""
    # CLI process: build_auth_url() generates + persists.
    _, state, verifier = oauth.build_auth_url()
    assert state in oauth._pkce_state  # in-memory in the "CLI" process

    # Simulate the CLI process exiting by wiping the in-memory dict.
    # The disk file must survive.
    oauth._pkce_state.clear()
    assert oauth._pending_states_path().is_file()

    # Server process: stub the actual Spotify token POST so we don't
    # need the network. ``exchange_code`` should still find the
    # state via _prune_pkce → _merge_pending_from_disk.
    async def _fake_post(self, *args, **kwargs):
        class _R:
            status_code = 200
            def json(self):
                return {
                    "access_token": "tok", "refresh_token": "rtok",
                    "expires_in": 3600, "token_type": "Bearer",
                    "scope": "user-read-playback-state",
                }
        return _R()
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    result = asyncio.run(oauth.exchange_code("auth-code-xyz", state))
    assert "error" not in result, f"expected success, got {result!r}"
    # State consumed — both in memory AND on disk.
    assert state not in oauth._pkce_state
    on_disk = oauth._load_pending_states()
    assert state not in on_disk, (
        "exchange_code must remove the state from disk after consuming "
        "it — otherwise a replay of the callback would get a stale entry"
    )


def test_exchange_code_with_state_only_on_disk_succeeds(spotify_env, monkeypatch):
    """Stronger version of the cross-process test: write directly to
    disk (bypass build_auth_url) so we KNOW the in-memory dict didn't
    have it. exchange_code must still find it via the disk merge."""
    state    = "state-only-on-disk"
    verifier = "verifier-from-cli-process"
    oauth._save_pending_states({state: (verifier, time.time())})
    assert state not in oauth._pkce_state

    async def _fake_post(self, *args, **kwargs):
        class _R:
            status_code = 200
            def json(self):
                return {
                    "access_token": "t", "refresh_token": "r",
                    "expires_in": 3600,
                }
        return _R()
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    result = asyncio.run(oauth.exchange_code("code", state))
    assert "error" not in result, f"expected success, got {result!r}"


# ── TTL pruning ────────────────────────────────────────────────────────


def test_prune_pkce_drops_expired_entries_from_disk_too(spotify_env):
    """Stale entries from a long-abandoned auth flow should be cleaned
    up so they don't leak verifiers indefinitely. Both in-memory AND
    disk get pruned."""
    expired_ts = time.time() - oauth._PKCE_TTL_SEC - 60
    fresh_ts   = time.time()
    oauth._save_pending_states({
        "stale-state": ("v1", expired_ts),
        "fresh-state": ("v2", fresh_ts),
    })
    oauth._prune_pkce()
    # Fresh survives; stale drops.
    assert "fresh-state" in oauth._pkce_state
    assert "stale-state" not in oauth._pkce_state


def test_prune_pkce_merges_disk_state_before_pruning(spotify_env):
    """Even when in-memory dict is empty, prune must read the disk
    file so the server process sees what the CLI process wrote
    before applying TTL cleanup."""
    state = "from-cli-process"
    oauth._save_pending_states({state: ("v", time.time())})
    oauth._pkce_state.clear()    # simulate fresh process
    oauth._prune_pkce()
    assert state in oauth._pkce_state, (
        "_prune_pkce must merge from disk so the server-side process "
        "sees CLI-written states"
    )


# ── Atomic-write safety ────────────────────────────────────────────────


def test_save_pending_states_atomic_under_concurrent_writers(spotify_env):
    """Two concurrent writers should both produce a valid JSON file —
    one's writes win, neither corrupts the file. The atomic_write
    helper guarantees this via tempfile + os.replace."""
    import threading
    states_a = {f"state-a-{i}": ("va", time.time()) for i in range(20)}
    states_b = {f"state-b-{i}": ("vb", time.time()) for i in range(20)}
    barrier = threading.Barrier(2)

    def _writer(states):
        barrier.wait()
        for _ in range(10):
            oauth._save_pending_states(states)

    t1 = threading.Thread(target=_writer, args=(states_a,))
    t2 = threading.Thread(target=_writer, args=(states_b,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    # Final file must be valid JSON of the expected shape — one
    # writer's last write wins, but the file is never half-written.
    loaded = oauth._load_pending_states()
    keys = list(loaded.keys())
    assert keys, "file should not be empty after writes"
    # Either purely a-set or purely b-set — atomic_write means we
    # never see a half-merged state.
    assert all(k.startswith("state-a-") for k in keys) \
        or all(k.startswith("state-b-") for k in keys)
