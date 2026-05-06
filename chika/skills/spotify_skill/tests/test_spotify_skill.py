"""Coverage for chika/skills/spotify_skill — all handlers + OAuth helpers.

The handlers are thin wrappers around `_req` that build the right URL and
params, so we mock `_req` and assert each handler dispatches correctly.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from chika.skills import spotify_skill as ss
from chika.skills.spotify_skill import oauth as oa

# ── _req call assertion helper ─────────────────────────────────────────


@pytest.fixture
def mock_req():
    with patch.object(ss, "_req", new_callable=AsyncMock) as m:
        m.return_value = {"ok": True}
        yield m


def _assert_called(mock, method, path, **kwargs):
    """Sugar — asserts _req was called with these positional+kwargs."""
    args, call_kwargs = mock.call_args
    assert args[0] == method
    assert args[1] == path
    for k, v in kwargs.items():
        assert call_kwargs.get(k) == v, f"{k} mismatch: {call_kwargs.get(k)!r} != {v!r}"


# ── _get_client_token ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_client_token_no_credentials(monkeypatch):
    monkeypatch.setattr(ss, "CLIENT_ID", "")
    monkeypatch.setattr(ss, "CLIENT_SECRET", "")
    monkeypatch.setattr(ss, "_client_token_cache", {})
    out = await ss._get_client_token()
    assert out == ""


@pytest.mark.asyncio
async def test_get_client_token_uses_cache(monkeypatch):
    monkeypatch.setattr(
        ss, "_client_token_cache",
        {"token": "cached-tok", "exp": time.time() + 1000},
    )
    out = await ss._get_client_token()
    assert out == "cached-tok"


@pytest.mark.asyncio
async def test_get_client_token_fetches_new(monkeypatch):
    monkeypatch.setattr(ss, "CLIENT_ID", "id")
    monkeypatch.setattr(ss, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(ss, "_client_token_cache", {})

    fake_resp = type("R", (), {"json": lambda self: {"access_token": "T", "expires_in": 3600}})()

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **k): return fake_resp

    with patch.object(ss.httpx, "AsyncClient", FakeClient):
        out = await ss._get_client_token()
    assert out == "T"


# ── _req method dispatch ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_req_returns_no_token_error(monkeypatch):
    async def empty_token(): return ""
    monkeypatch.setattr(ss, "_get_client_token", empty_token)
    out = await ss._req("GET", "/anything")
    assert "error" in out
    assert "token" in out["error"].lower()


def _make_fake_client(resp_factory):
    """Build a FakeClient class whose every HTTP method returns the same fake response."""
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **k): return resp_factory()
        async def post(self, *a, **k): return resp_factory()
        async def put(self, *a, **k): return resp_factory()
        async def delete(self, *a, **k): return resp_factory()
    return FakeClient


@pytest.mark.asyncio
async def test_req_unknown_method(monkeypatch):
    async def t(): return "T"
    monkeypatch.setattr(ss, "_get_client_token", t)
    Fake = _make_fake_client(lambda: type("R", (), {"status_code": 200})())
    with patch.object(ss.httpx, "AsyncClient", Fake):
        out = await ss._req("PATCH", "/foo")
    assert "error" in out
    assert "Unknown method" in out["error"]


@pytest.mark.asyncio
async def test_req_204_returns_ok(monkeypatch):
    async def t(): return "T"
    monkeypatch.setattr(ss, "_get_client_token", t)
    Fake = _make_fake_client(lambda: type("R", (), {"status_code": 204})())
    with patch.object(ss.httpx, "AsyncClient", Fake):
        out = await ss._req("GET", "/foo")
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_req_returns_json_body(monkeypatch):
    async def t(): return "T"
    monkeypatch.setattr(ss, "_get_client_token", t)
    Fake = _make_fake_client(
        lambda: type(
            "R", (),
            {"status_code": 200, "json": lambda self: {"id": "x"}},
        )()
    )
    with patch.object(ss.httpx, "AsyncClient", Fake):
        out = await ss._req("GET", "/foo")
    assert out == {"id": "x"}


@pytest.mark.asyncio
async def test_req_falls_back_on_json_failure(monkeypatch):
    async def t(): return "T"
    monkeypatch.setattr(ss, "_get_client_token", t)

    def boom(self): raise ValueError("not json")
    Fake = _make_fake_client(
        lambda: type(
            "R", (),
            {"status_code": 502, "json": boom, "text": "Bad gateway"},
        )()
    )
    with patch.object(ss.httpx, "AsyncClient", Fake):
        out = await ss._req("GET", "/foo")
    assert out["status_code"] == 502
    assert "Bad gateway" in out["text"]


@pytest.mark.asyncio
async def test_req_post_method(monkeypatch):
    async def t(): return "T"
    monkeypatch.setattr(ss, "_get_user_token", t)
    Fake = _make_fake_client(
        lambda: type("R", (), {"status_code": 200, "json": lambda self: {"posted": True}})()
    )
    with patch.object(ss.httpx, "AsyncClient", Fake):
        out = await ss._req("POST", "/foo", user_auth=True, json_body={"x": 1})
    assert out == {"posted": True}


@pytest.mark.asyncio
async def test_req_put_method(monkeypatch):
    async def t(): return "T"
    monkeypatch.setattr(ss, "_get_client_token", t)
    Fake = _make_fake_client(lambda: type("R", (), {"status_code": 204})())
    with patch.object(ss.httpx, "AsyncClient", Fake):
        out = await ss._req("PUT", "/foo")
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_req_delete_method(monkeypatch):
    async def t(): return "T"
    monkeypatch.setattr(ss, "_get_client_token", t)
    Fake = _make_fake_client(lambda: type("R", (), {"status_code": 204})())
    with patch.object(ss.httpx, "AsyncClient", Fake):
        out = await ss._req("DELETE", "/foo")
    assert out == {"ok": True}


# ── auth tools ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spotify_auth_status_authorized(monkeypatch):
    monkeypatch.setattr(
        oa, "auth_status", lambda: {"authorized": True, "needs_reauth": False},
    )
    out = await ss.spotify_auth_status()
    assert out["authorized"] is True


@pytest.mark.asyncio
async def test_spotify_auth_status_tries_refresh(monkeypatch):
    """When not authorized but has refresh token, refresh is attempted."""
    calls = []
    monkeypatch.setattr(
        oa, "auth_status",
        lambda: {"authorized": False, "needs_reauth": False},
    )
    async def refresh(): calls.append("refresh"); return "newtok"
    monkeypatch.setattr(oa, "refresh_access_token", refresh)
    out = await ss.spotify_auth_status()
    assert "refresh" in calls
    assert out is not None


@pytest.mark.asyncio
async def test_spotify_get_auth_url_no_client_id(monkeypatch):
    monkeypatch.setattr(ss, "CLIENT_ID", "")
    out = await ss.spotify_get_auth_url()
    assert "error" in out


@pytest.mark.asyncio
async def test_spotify_get_auth_url_returns_url(monkeypatch):
    monkeypatch.setattr(ss, "CLIENT_ID", "abc")
    monkeypatch.setattr(
        oa, "build_auth_url", lambda: ("https://x", "state", "verifier"),
    )
    out = await ss.spotify_get_auth_url()
    assert out["url"] == "https://x"
    assert "browser" in out["instruction"].lower()


# ── search / tracks / artists / albums / playlists ─────────────────────


@pytest.mark.asyncio
async def test_spotify_search_basic(mock_req):
    await ss.spotify_search(query="abc")
    args, kwargs = mock_req.call_args
    assert args[1] == "/search"
    assert kwargs["params"]["q"] == "abc"
    assert kwargs["params"]["limit"] == 10


@pytest.mark.asyncio
async def test_spotify_search_caps_limit_at_50(mock_req):
    await ss.spotify_search(query="x", limit=999)
    assert mock_req.call_args[1]["params"]["limit"] == 50


@pytest.mark.asyncio
async def test_spotify_search_with_market(mock_req):
    await ss.spotify_search(query="x", market="US")
    assert mock_req.call_args[1]["params"]["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_track(mock_req):
    await ss.spotify_get_track(track_id="abc", market="GB")
    _assert_called(mock_req, "GET", "/tracks/abc", params={"market": "GB"})


@pytest.mark.asyncio
async def test_spotify_get_track_no_market(mock_req):
    await ss.spotify_get_track(track_id="abc")
    _assert_called(mock_req, "GET", "/tracks/abc", params={})


@pytest.mark.asyncio
async def test_spotify_get_tracks(mock_req):
    await ss.spotify_get_tracks(ids="a,b,c")
    _assert_called(mock_req, "GET", "/tracks", params={"ids": "a,b,c"})


@pytest.mark.asyncio
async def test_spotify_get_audio_features(mock_req):
    await ss.spotify_get_audio_features(track_id="t")
    _assert_called(mock_req, "GET", "/audio-features/t")


@pytest.mark.asyncio
async def test_spotify_get_recommendations(mock_req):
    await ss.spotify_get_recommendations(
        seed_tracks="t1", seed_artists="a1", seed_genres="rock",
        limit=5, min_energy=0.5,
    )
    args, kwargs = mock_req.call_args
    assert args[1] == "/recommendations"
    p = kwargs["params"]
    assert p["seed_tracks"] == "t1"
    assert p["seed_artists"] == "a1"
    assert p["seed_genres"] == "rock"
    assert p["limit"] == 5
    assert p["min_energy"] == 0.5


@pytest.mark.asyncio
async def test_spotify_get_album(mock_req):
    await ss.spotify_get_album(album_id="al", market="DE")
    _assert_called(mock_req, "GET", "/albums/al", params={"market": "DE"})


@pytest.mark.asyncio
async def test_spotify_get_album_no_market(mock_req):
    await ss.spotify_get_album(album_id="al")
    _assert_called(mock_req, "GET", "/albums/al", params={})


@pytest.mark.asyncio
async def test_spotify_get_album_tracks(mock_req):
    await ss.spotify_get_album_tracks(album_id="al", limit=5, offset=10, market="US")
    p = mock_req.call_args[1]["params"]
    assert p["limit"] == 5 and p["offset"] == 10 and p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_new_releases(mock_req):
    await ss.spotify_get_new_releases(country="US", limit=5)
    p = mock_req.call_args[1]["params"]
    assert p["country"] == "US" and p["limit"] == 5


@pytest.mark.asyncio
async def test_spotify_get_artist(mock_req):
    await ss.spotify_get_artist(artist_id="ar")
    _assert_called(mock_req, "GET", "/artists/ar")


@pytest.mark.asyncio
async def test_spotify_get_artist_albums(mock_req):
    await ss.spotify_get_artist_albums(artist_id="ar", market="US")
    p = mock_req.call_args[1]["params"]
    assert p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_artist_top_tracks(mock_req):
    await ss.spotify_get_artist_top_tracks(artist_id="ar")
    _assert_called(mock_req, "GET", "/artists/ar/top-tracks", params={"market": "US"})


@pytest.mark.asyncio
async def test_spotify_get_related_artists(mock_req):
    await ss.spotify_get_related_artists(artist_id="ar")
    _assert_called(mock_req, "GET", "/artists/ar/related-artists")


@pytest.mark.asyncio
async def test_spotify_get_playlist(mock_req):
    await ss.spotify_get_playlist(playlist_id="pl", fields="tracks", market="US")
    p = mock_req.call_args[1]["params"]
    assert p["fields"] == "tracks" and p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_playlist_tracks(mock_req):
    await ss.spotify_get_playlist_tracks(
        playlist_id="pl", limit=5, fields="x", market="US",
    )
    p = mock_req.call_args[1]["params"]
    assert p["limit"] == 5 and p["fields"] == "x" and p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_create_playlist(mock_req):
    await ss.spotify_create_playlist(
        user_id="u", name="My PL", description="d", public=True,
    )
    args, kwargs = mock_req.call_args
    assert args[0] == "POST"
    assert args[1] == "/users/u/playlists"
    assert kwargs["json_body"]["name"] == "My PL"
    assert kwargs["user_auth"] is True


@pytest.mark.asyncio
async def test_spotify_add_to_playlist(mock_req):
    await ss.spotify_add_to_playlist(playlist_id="pl", uris="u1,u2", position=0)
    body = mock_req.call_args[1]["json_body"]
    assert body["uris"] == ["u1", "u2"]
    assert body["position"] == 0


@pytest.mark.asyncio
async def test_spotify_add_to_playlist_no_position(mock_req):
    await ss.spotify_add_to_playlist(playlist_id="pl", uris="u1")
    body = mock_req.call_args[1]["json_body"]
    assert "position" not in body


@pytest.mark.asyncio
async def test_spotify_remove_from_playlist(mock_req):
    await ss.spotify_remove_from_playlist(playlist_id="pl", uris="u1, u2")
    body = mock_req.call_args[1]["json_body"]
    assert body["tracks"] == [{"uri": "u1"}, {"uri": "u2"}]


@pytest.mark.asyncio
async def test_spotify_featured_playlists(mock_req):
    await ss.spotify_featured_playlists(country="US", limit=5)
    p = mock_req.call_args[1]["params"]
    assert p["country"] == "US"


@pytest.mark.asyncio
async def test_spotify_category_playlists(mock_req):
    await ss.spotify_category_playlists(category_id="rock", country="US", limit=3)
    args, _ = mock_req.call_args
    assert args[1] == "/browse/categories/rock/playlists"


@pytest.mark.asyncio
async def test_spotify_get_categories(mock_req):
    await ss.spotify_get_categories(country="US", limit=5)
    p = mock_req.call_args[1]["params"]
    assert p["country"] == "US" and p["limit"] == 5


@pytest.mark.asyncio
async def test_spotify_get_current_user(mock_req):
    await ss.spotify_get_current_user()
    args, kwargs = mock_req.call_args
    assert args[1] == "/me"
    assert kwargs["user_auth"] is True


@pytest.mark.asyncio
async def test_spotify_get_user(mock_req):
    await ss.spotify_get_user(user_id="u")
    _assert_called(mock_req, "GET", "/users/u")


@pytest.mark.asyncio
async def test_spotify_get_my_playlists(mock_req):
    await ss.spotify_get_my_playlists(limit=5, offset=2)
    args, kwargs = mock_req.call_args
    assert args[1] == "/me/playlists"
    assert kwargs["params"]["limit"] == 5
    assert kwargs["params"]["offset"] == 2


@pytest.mark.asyncio
async def test_spotify_get_my_top(mock_req):
    await ss.spotify_get_my_top(type="artists", time_range="long_term", limit=5)
    args, kwargs = mock_req.call_args
    assert args[1] == "/me/top/artists"
    assert kwargs["params"]["time_range"] == "long_term"


@pytest.mark.asyncio
async def test_spotify_get_recently_played(mock_req):
    await ss.spotify_get_recently_played(limit=5)
    args, kwargs = mock_req.call_args
    assert args[1] == "/me/player/recently-played"
    assert kwargs["params"]["limit"] == 5


@pytest.mark.asyncio
async def test_spotify_get_saved_tracks(mock_req):
    await ss.spotify_get_saved_tracks(limit=10, market="US")
    p = mock_req.call_args[1]["params"]
    assert p["limit"] == 10 and p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_save_tracks(mock_req):
    await ss.spotify_save_tracks(ids="t1,t2")
    body = mock_req.call_args[1]["json_body"]
    assert body["ids"] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_spotify_remove_saved_tracks(mock_req):
    await ss.spotify_remove_saved_tracks(ids="t1,t2")
    body = mock_req.call_args[1]["json_body"]
    assert body["ids"] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_spotify_check_saved_tracks(mock_req):
    await ss.spotify_check_saved_tracks(ids="t1,t2")
    args, kwargs = mock_req.call_args
    assert args[1] == "/me/tracks/contains"
    assert kwargs["params"]["ids"] == "t1,t2"


@pytest.mark.asyncio
async def test_spotify_get_saved_albums(mock_req):
    await ss.spotify_get_saved_albums()
    args, _ = mock_req.call_args
    assert args[1] == "/me/albums"


@pytest.mark.asyncio
async def test_spotify_save_albums(mock_req):
    await ss.spotify_save_albums(ids="a1,a2")
    body = mock_req.call_args[1]["json_body"]
    assert body["ids"] == ["a1", "a2"]


# ── follow ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spotify_follow_artist(mock_req):
    await ss.spotify_follow_artist(ids="ar1,ar2")
    args, kwargs = mock_req.call_args
    assert args[0] == "PUT"
    assert kwargs["params"]["type"] == "artist"
    assert kwargs["json_body"]["ids"] == ["ar1", "ar2"]


@pytest.mark.asyncio
async def test_spotify_unfollow_artist(mock_req):
    await ss.spotify_unfollow_artist(ids="ar")
    args, _ = mock_req.call_args
    assert args[0] == "DELETE"


@pytest.mark.asyncio
async def test_spotify_get_followed_artists(mock_req):
    await ss.spotify_get_followed_artists(limit=5)
    p = mock_req.call_args[1]["params"]
    assert p["type"] == "artist" and p["limit"] == 5


@pytest.mark.asyncio
async def test_spotify_follow_playlist(mock_req):
    await ss.spotify_follow_playlist(playlist_id="pl", public=False)
    args, kwargs = mock_req.call_args
    assert args[1] == "/playlists/pl/followers"
    assert kwargs["json_body"]["public"] is False


# ── player ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spotify_get_player_state(mock_req):
    await ss.spotify_get_player_state(market="US")
    p = mock_req.call_args[1]["params"]
    assert p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_currently_playing(mock_req):
    await ss.spotify_get_currently_playing(market="US")
    p = mock_req.call_args[1]["params"]
    assert p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_devices(mock_req):
    await ss.spotify_get_devices()
    args, _ = mock_req.call_args
    assert args[1] == "/me/player/devices"


@pytest.mark.asyncio
async def test_spotify_transfer_playback(mock_req):
    await ss.spotify_transfer_playback(device_id="d", play=False)
    body = mock_req.call_args[1]["json_body"]
    assert body["device_ids"] == ["d"]
    assert body["play"] is False


@pytest.mark.asyncio
async def test_spotify_play_with_context_uri(mock_req):
    await ss.spotify_play(context_uri="spotify:album:abc", offset=2, device_id="d")
    body = mock_req.call_args[1]["json_body"]
    assert body["context_uri"] == "spotify:album:abc"
    assert body["offset"] == {"position": 2}


@pytest.mark.asyncio
async def test_spotify_play_with_uris(mock_req):
    await ss.spotify_play(uris="u1,u2")
    body = mock_req.call_args[1]["json_body"]
    assert body["uris"] == ["u1", "u2"]


@pytest.mark.asyncio
async def test_spotify_play_no_args(mock_req):
    await ss.spotify_play()
    body = mock_req.call_args[1]["json_body"]
    assert body == {}


@pytest.mark.asyncio
async def test_spotify_pause(mock_req):
    await ss.spotify_pause(device_id="d")
    args, kwargs = mock_req.call_args
    assert args[1] == "/me/player/pause"
    assert kwargs["params"]["device_id"] == "d"


@pytest.mark.asyncio
async def test_spotify_pause_no_device(mock_req):
    await ss.spotify_pause()
    args, kwargs = mock_req.call_args
    assert kwargs["params"] == {}


@pytest.mark.asyncio
async def test_spotify_next(mock_req):
    await ss.spotify_next(device_id="d")
    args, _ = mock_req.call_args
    assert args[0] == "POST"
    assert args[1] == "/me/player/next"


@pytest.mark.asyncio
async def test_spotify_previous(mock_req):
    await ss.spotify_previous()
    args, _ = mock_req.call_args
    assert args[1] == "/me/player/previous"


@pytest.mark.asyncio
async def test_spotify_seek(mock_req):
    await ss.spotify_seek(position_ms=5000, device_id="d")
    p = mock_req.call_args[1]["params"]
    assert p["position_ms"] == 5000 and p["device_id"] == "d"


@pytest.mark.asyncio
async def test_spotify_set_volume_clamps_high(mock_req):
    await ss.spotify_set_volume(volume_percent=999)
    assert mock_req.call_args[1]["params"]["volume_percent"] == 100


@pytest.mark.asyncio
async def test_spotify_set_volume_clamps_low(mock_req):
    await ss.spotify_set_volume(volume_percent=-10)
    assert mock_req.call_args[1]["params"]["volume_percent"] == 0


@pytest.mark.asyncio
async def test_spotify_set_shuffle(mock_req):
    await ss.spotify_set_shuffle(state=True, device_id="d")
    p = mock_req.call_args[1]["params"]
    assert p["state"] is True and p["device_id"] == "d"


@pytest.mark.asyncio
async def test_spotify_set_repeat(mock_req):
    await ss.spotify_set_repeat(state="track")
    p = mock_req.call_args[1]["params"]
    assert p["state"] == "track"


@pytest.mark.asyncio
async def test_spotify_add_to_queue(mock_req):
    await ss.spotify_add_to_queue(uri="spotify:track:abc", device_id="d")
    p = mock_req.call_args[1]["params"]
    assert p["uri"] == "spotify:track:abc"


@pytest.mark.asyncio
async def test_spotify_get_queue(mock_req):
    await ss.spotify_get_queue()
    args, _ = mock_req.call_args
    assert args[1] == "/me/player/queue"


# ── shows / episodes / markets ────────────────────────────────────────


@pytest.mark.asyncio
async def test_spotify_get_show(mock_req):
    await ss.spotify_get_show(show_id="s", market="US")
    p = mock_req.call_args[1]["params"]
    assert p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_show_episodes(mock_req):
    await ss.spotify_get_show_episodes(show_id="s", limit=5, market="US")
    p = mock_req.call_args[1]["params"]
    assert p["limit"] == 5 and p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_episode(mock_req):
    await ss.spotify_get_episode(episode_id="e", market="US")
    p = mock_req.call_args[1]["params"]
    assert p["market"] == "US"


@pytest.mark.asyncio
async def test_spotify_get_markets(mock_req):
    await ss.spotify_get_markets()
    args, _ = mock_req.call_args
    assert args[1] == "/markets"


# ── _td & SPOTIFY_TOOLS ────────────────────────────────────────────────


def test_spotify_tools_list_exposes_handlers():
    """All tools have a callable handler."""
    for tool in ss.SPOTIFY_TOOLS:
        assert callable(tool.handler), tool.name
        assert tool.parameters["type"] == "object"


def test_spotify_tools_unique_names():
    names = [t.name for t in ss.SPOTIFY_TOOLS]
    assert len(names) == len(set(names))


# ── oauth helpers ──────────────────────────────────────────────────────


# OAuth-internals tests have moved to chika/skills/spotify_skill/tests/.
# That suite now owns:
#   - PKCE primitives (verifier / challenge / state CSRF + TTL prune)
#   - Per-profile token storage (atomic write, isolation, share-mode,
#     per-profile override)
#   - Exchange + refresh paths (happy, 4xx, network failure, invalid_grant
#     wipes RT, rotating-RT honoured, concurrent-refresh lock)
#   - get_valid_access_token cache vs refresh decision
#   - auth_status redaction guarantees
#   - connection.py helpers (start_connect, fetch_profile, status, disconnect)
#   - HTTP route handlers (status / connect / disconnect / callback)
#   - CLI subcommand + slash command
# That keeps OAuth tests next to the skill they test, per the
# convention all_skill_specific_tests_stay_inside_the_skill_dir.

