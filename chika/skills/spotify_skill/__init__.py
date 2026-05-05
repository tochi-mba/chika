"""
Spotify Skill — full Spotify Web API access.

Covers:
  Search, Albums, Artists, Tracks, Playlists, Browse/Featured,
  Player (playback, queue, devices, seek, volume, shuffle, repeat),
  User library (saved tracks/albums/shows/episodes),
  User profile, Follow, Recommendations, Markets, Podcasts/Shows/Episodes

Auth:
  Client credentials (catalog): CHIKA_SPOTIFY_CLIENT_ID + CHIKA_SPOTIFY_CLIENT_SECRET
  User OAuth (playback/library): CHIKA_SPOTIFY_ACCESS_TOKEN (or refresh flow)
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any, cast

import httpx

from chika.core.skill_registry import Skill
from chika.core.tool_registry import ToolDefinition
from chika.skills.spotify_skill import oauth as _oauth

# ── Env ───────────────────────────────────────────────────────────────────────
CLIENT_ID     = os.getenv("CHIKA_SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CHIKA_SPOTIFY_CLIENT_SECRET", "")

_client_token_cache: dict[str, Any] = {}

BASE = "https://api.spotify.com/v1"

# ── Auth helpers ──────────────────────────────────────────────────────────────

async def _get_client_token() -> str:
    now = time.time()
    if _client_token_cache.get("exp", 0) > now:
        return _client_token_cache["token"]
    if not CLIENT_ID or not CLIENT_SECRET:
        return ""
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {creds}"},
        )
        data = r.json()
    token = data.get("access_token", "")
    _client_token_cache["token"] = token
    _client_token_cache["exp"] = now + data.get("expires_in", 3600) - 60
    return token


async def _get_user_token() -> str:
    return await _oauth.get_valid_access_token()


# ── OAuth tools (exposed to agent) ───────────────────────────────────────────

async def spotify_auth_status() -> dict:
    """Check Spotify OAuth status."""
    status = _oauth.auth_status()
    if not status["authorized"] and not status["needs_reauth"]:
        # Try to refresh
        token = await _oauth.refresh_access_token()
        if token:
            status = _oauth.auth_status()
    return status


async def spotify_get_auth_url() -> dict:
    """Generate the Spotify OAuth authorization URL. User must open this link."""
    if not CLIENT_ID:
        return {"error": "CHIKA_SPOTIFY_CLIENT_ID not set"}
    url, state, _ = _oauth.build_auth_url()
    return {
        "url": url,
        "instruction": f"Open this URL in your browser to authorize Chika: {url}",
        "callback_endpoint": _oauth.REDIRECT_URI,
    }


async def _req(
    method: str,
    path: str,
    user_auth: bool = False,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict:
    token = await _get_user_token() if user_auth else await _get_client_token()
    if not token:
        return {"error": "No Spotify token available. Set CHIKA_SPOTIFY_ACCESS_TOKEN or CLIENT_ID+SECRET."}
    headers = {"Authorization": f"Bearer {token}"}
    url = BASE + path
    async with httpx.AsyncClient(timeout=15) as client:
        if method == "GET":
            r = await client.get(url, headers=headers, params=params)
        elif method == "POST":
            r = await client.post(url, headers=headers, params=params, json=json_body)
        elif method == "PUT":
            r = await client.put(url, headers=headers, params=params, json=json_body)
        elif method == "DELETE":
            r = await client.delete(url, headers=headers, params=params, json=json_body)  # type: ignore[call-arg]
        else:
            return {"error": f"Unknown method: {method}"}
    if r.status_code == 204:
        return {"ok": True}
    try:
        return cast(dict, r.json())
    except Exception:
        return {"status_code": r.status_code, "text": r.text[:500]}

# ── Tool implementations ──────────────────────────────────────────────────────

# SEARCH
async def spotify_search(query: str, type: str = "track", limit: int = 10, offset: int = 0, market: str = "") -> dict:
    params = {"q": query, "type": type, "limit": min(limit, 50), "offset": offset}
    if market: params["market"] = market
    return await _req("GET", "/search", params=params)

# TRACKS
async def spotify_get_track(track_id: str, market: str = "") -> dict:
    params = {"market": market} if market else {}
    return await _req("GET", f"/tracks/{track_id}", params=params)

async def spotify_get_tracks(ids: str) -> dict:
    return await _req("GET", "/tracks", params={"ids": ids})

async def spotify_get_audio_features(track_id: str) -> dict:
    return await _req("GET", f"/audio-features/{track_id}")

async def spotify_get_recommendations(seed_tracks: str = "", seed_artists: str = "", seed_genres: str = "", limit: int = 10, **kwargs) -> dict:
    params: dict[str, Any] = {"limit": limit}
    if seed_tracks:  params["seed_tracks"]  = seed_tracks
    if seed_artists: params["seed_artists"] = seed_artists
    if seed_genres:  params["seed_genres"]  = seed_genres
    params.update(kwargs)
    return await _req("GET", "/recommendations", params=params)

# ALBUMS
async def spotify_get_album(album_id: str, market: str = "") -> dict:
    params = {"market": market} if market else {}
    return await _req("GET", f"/albums/{album_id}", params=params)

async def spotify_get_album_tracks(album_id: str, limit: int = 20, offset: int = 0, market: str = "") -> dict:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if market: params["market"] = market
    return await _req("GET", f"/albums/{album_id}/tracks", params=params)

async def spotify_get_new_releases(country: str = "", limit: int = 20) -> dict:
    params: dict = {"limit": limit}
    if country: params["country"] = country
    return await _req("GET", "/browse/new-releases", params=params)

# ARTISTS
async def spotify_get_artist(artist_id: str) -> dict:
    return await _req("GET", f"/artists/{artist_id}")

async def spotify_get_artist_albums(artist_id: str, include_groups: str = "album,single", limit: int = 20, market: str = "") -> dict:
    params = {"include_groups": include_groups, "limit": limit}
    if market: params["market"] = market
    return await _req("GET", f"/artists/{artist_id}/albums", params=params)

async def spotify_get_artist_top_tracks(artist_id: str, market: str = "US") -> dict:
    return await _req("GET", f"/artists/{artist_id}/top-tracks", params={"market": market})

async def spotify_get_related_artists(artist_id: str) -> dict:
    return await _req("GET", f"/artists/{artist_id}/related-artists")

# PLAYLISTS
async def spotify_get_playlist(playlist_id: str, fields: str = "", market: str = "") -> dict:
    params: dict = {}
    if fields: params["fields"] = fields
    if market: params["market"] = market
    return await _req("GET", f"/playlists/{playlist_id}", params=params)

async def spotify_get_playlist_tracks(playlist_id: str, limit: int = 20, offset: int = 0, fields: str = "", market: str = "") -> dict:
    params: dict = {"limit": limit, "offset": offset}
    if fields: params["fields"] = fields
    if market: params["market"] = market
    return await _req("GET", f"/playlists/{playlist_id}/tracks", params=params)

async def spotify_create_playlist(user_id: str, name: str, description: str = "", public: bool = False) -> dict:
    return await _req("POST", f"/users/{user_id}/playlists", user_auth=True,
                      json_body={"name": name, "description": description, "public": public})

async def spotify_add_to_playlist(playlist_id: str, uris: str, position: int | None = None) -> dict:
    body: dict = {"uris": uris.split(",")}
    if position is not None: body["position"] = position
    return await _req("POST", f"/playlists/{playlist_id}/tracks", user_auth=True, json_body=body)

async def spotify_remove_from_playlist(playlist_id: str, uris: str) -> dict:
    tracks = [{"uri": u.strip()} for u in uris.split(",")]
    return await _req("DELETE", f"/playlists/{playlist_id}/tracks", user_auth=True, json_body={"tracks": tracks})

async def spotify_featured_playlists(country: str = "", limit: int = 10) -> dict:
    params: dict = {"limit": limit}
    if country: params["country"] = country
    return await _req("GET", "/browse/featured-playlists", params=params)

async def spotify_category_playlists(category_id: str, country: str = "", limit: int = 10) -> dict:
    params: dict = {"limit": limit}
    if country: params["country"] = country
    return await _req("GET", f"/browse/categories/{category_id}/playlists", params=params)

# BROWSE / CATEGORIES
async def spotify_get_categories(country: str = "", limit: int = 20) -> dict:
    params: dict = {"limit": limit}
    if country: params["country"] = country
    return await _req("GET", "/browse/categories", params=params)

# USER
async def spotify_get_current_user() -> dict:
    return await _req("GET", "/me", user_auth=True)

async def spotify_get_user(user_id: str) -> dict:
    return await _req("GET", f"/users/{user_id}")

async def spotify_get_my_playlists(limit: int = 20, offset: int = 0) -> dict:
    return await _req("GET", "/me/playlists", user_auth=True, params={"limit": limit, "offset": offset})

async def spotify_get_my_top(type: str = "tracks", time_range: str = "medium_term", limit: int = 20) -> dict:
    return await _req("GET", f"/me/top/{type}", user_auth=True, params={"time_range": time_range, "limit": limit})

async def spotify_get_recently_played(limit: int = 20) -> dict:
    return await _req("GET", "/me/player/recently-played", user_auth=True, params={"limit": limit})

# LIBRARY
async def spotify_get_saved_tracks(limit: int = 20, offset: int = 0, market: str = "") -> dict:
    params: dict = {"limit": limit, "offset": offset}
    if market: params["market"] = market
    return await _req("GET", "/me/tracks", user_auth=True, params=params)

async def spotify_save_tracks(ids: str) -> dict:
    return await _req("PUT", "/me/tracks", user_auth=True, json_body={"ids": ids.split(",")})

async def spotify_remove_saved_tracks(ids: str) -> dict:
    return await _req("DELETE", "/me/tracks", user_auth=True, json_body={"ids": ids.split(",")})

async def spotify_check_saved_tracks(ids: str) -> dict:
    return await _req("GET", "/me/tracks/contains", user_auth=True, params={"ids": ids})

async def spotify_get_saved_albums(limit: int = 20, offset: int = 0) -> dict:
    return await _req("GET", "/me/albums", user_auth=True, params={"limit": limit, "offset": offset})

async def spotify_save_albums(ids: str) -> dict:
    return await _req("PUT", "/me/albums", user_auth=True, json_body={"ids": ids.split(",")})

# FOLLOW
async def spotify_follow_artist(ids: str) -> dict:
    return await _req("PUT", "/me/following", user_auth=True, params={"type": "artist"},
                      json_body={"ids": ids.split(",")})

async def spotify_unfollow_artist(ids: str) -> dict:
    return await _req("DELETE", "/me/following", user_auth=True, params={"type": "artist"},
                      json_body={"ids": ids.split(",")})

async def spotify_get_followed_artists(limit: int = 20) -> dict:
    return await _req("GET", "/me/following", user_auth=True, params={"type": "artist", "limit": limit})

async def spotify_follow_playlist(playlist_id: str, public: bool = True) -> dict:
    return await _req("PUT", f"/playlists/{playlist_id}/followers", user_auth=True, json_body={"public": public})

# PLAYER
async def spotify_get_player_state(market: str = "") -> dict:
    params = {"market": market} if market else {}
    return await _req("GET", "/me/player", user_auth=True, params=params)

async def spotify_get_currently_playing(market: str = "") -> dict:
    params = {"market": market} if market else {}
    return await _req("GET", "/me/player/currently-playing", user_auth=True, params=params)

async def spotify_get_devices() -> dict:
    return await _req("GET", "/me/player/devices", user_auth=True)

async def spotify_transfer_playback(device_id: str, play: bool = True) -> dict:
    return await _req("PUT", "/me/player", user_auth=True, json_body={"device_ids": [device_id], "play": play})

async def spotify_play(uris: str = "", context_uri: str = "", device_id: str = "", offset: int | None = None) -> dict:
    body: dict = {}
    if uris:        body["uris"] = uris.split(",")
    if context_uri: body["context_uri"] = context_uri
    if offset is not None: body["offset"] = {"position": offset}
    params = {"device_id": device_id} if device_id else {}
    return await _req("PUT", "/me/player/play", user_auth=True, params=params, json_body=body)

async def spotify_pause(device_id: str = "") -> dict:
    params = {"device_id": device_id} if device_id else {}
    return await _req("PUT", "/me/player/pause", user_auth=True, params=params)

async def spotify_next(device_id: str = "") -> dict:
    params = {"device_id": device_id} if device_id else {}
    return await _req("POST", "/me/player/next", user_auth=True, params=params)

async def spotify_previous(device_id: str = "") -> dict:
    params = {"device_id": device_id} if device_id else {}
    return await _req("POST", "/me/player/previous", user_auth=True, params=params)

async def spotify_seek(position_ms: int, device_id: str = "") -> dict:
    params: dict = {"position_ms": position_ms}
    if device_id: params["device_id"] = device_id
    return await _req("PUT", "/me/player/seek", user_auth=True, params=params)

async def spotify_set_volume(volume_percent: int, device_id: str = "") -> dict:
    params: dict = {"volume_percent": max(0, min(100, volume_percent))}
    if device_id: params["device_id"] = device_id
    return await _req("PUT", "/me/player/volume", user_auth=True, params=params)

async def spotify_set_shuffle(state: bool, device_id: str = "") -> dict:
    params: dict = {"state": state}
    if device_id: params["device_id"] = device_id
    return await _req("PUT", "/me/player/shuffle", user_auth=True, params=params)

async def spotify_set_repeat(state: str, device_id: str = "") -> dict:
    params: dict = {"state": state}  # off | track | context
    if device_id: params["device_id"] = device_id
    return await _req("PUT", "/me/player/repeat", user_auth=True, params=params)

async def spotify_add_to_queue(uri: str, device_id: str = "") -> dict:
    params: dict = {"uri": uri}
    if device_id: params["device_id"] = device_id
    return await _req("POST", "/me/player/queue", user_auth=True, params=params)

async def spotify_get_queue() -> dict:
    return await _req("GET", "/me/player/queue", user_auth=True)

# SHOWS / PODCASTS
async def spotify_get_show(show_id: str, market: str = "") -> dict:
    params = {"market": market} if market else {}
    return await _req("GET", f"/shows/{show_id}", params=params)

async def spotify_get_show_episodes(show_id: str, limit: int = 20, offset: int = 0, market: str = "") -> dict:
    params: dict = {"limit": limit, "offset": offset}
    if market: params["market"] = market
    return await _req("GET", f"/shows/{show_id}/episodes", params=params)

async def spotify_get_episode(episode_id: str, market: str = "") -> dict:
    params = {"market": market} if market else {}
    return await _req("GET", f"/episodes/{episode_id}", params=params)

# MARKETS
async def spotify_get_markets() -> dict:
    return await _req("GET", "/markets")

# ── Tool definitions ──────────────────────────────────────────────────────────

def _td(name, desc, props, required=None, user_auth=False):
    handler_map = {
        "spotify_auth_status":  spotify_auth_status,
        "spotify_get_auth_url": spotify_get_auth_url,
        "spotify_search": spotify_search,
        "spotify_get_track": spotify_get_track,
        "spotify_get_tracks": spotify_get_tracks,
        "spotify_get_audio_features": spotify_get_audio_features,
        "spotify_get_recommendations": spotify_get_recommendations,
        "spotify_get_album": spotify_get_album,
        "spotify_get_album_tracks": spotify_get_album_tracks,
        "spotify_get_new_releases": spotify_get_new_releases,
        "spotify_get_artist": spotify_get_artist,
        "spotify_get_artist_albums": spotify_get_artist_albums,
        "spotify_get_artist_top_tracks": spotify_get_artist_top_tracks,
        "spotify_get_related_artists": spotify_get_related_artists,
        "spotify_get_playlist": spotify_get_playlist,
        "spotify_get_playlist_tracks": spotify_get_playlist_tracks,
        "spotify_create_playlist": spotify_create_playlist,
        "spotify_add_to_playlist": spotify_add_to_playlist,
        "spotify_remove_from_playlist": spotify_remove_from_playlist,
        "spotify_featured_playlists": spotify_featured_playlists,
        "spotify_category_playlists": spotify_category_playlists,
        "spotify_get_categories": spotify_get_categories,
        "spotify_get_current_user": spotify_get_current_user,
        "spotify_get_user": spotify_get_user,
        "spotify_get_my_playlists": spotify_get_my_playlists,
        "spotify_get_my_top": spotify_get_my_top,
        "spotify_get_recently_played": spotify_get_recently_played,
        "spotify_get_saved_tracks": spotify_get_saved_tracks,
        "spotify_save_tracks": spotify_save_tracks,
        "spotify_remove_saved_tracks": spotify_remove_saved_tracks,
        "spotify_check_saved_tracks": spotify_check_saved_tracks,
        "spotify_get_saved_albums": spotify_get_saved_albums,
        "spotify_save_albums": spotify_save_albums,
        "spotify_follow_artist": spotify_follow_artist,
        "spotify_unfollow_artist": spotify_unfollow_artist,
        "spotify_get_followed_artists": spotify_get_followed_artists,
        "spotify_follow_playlist": spotify_follow_playlist,
        "spotify_get_player_state": spotify_get_player_state,
        "spotify_get_currently_playing": spotify_get_currently_playing,
        "spotify_get_devices": spotify_get_devices,
        "spotify_transfer_playback": spotify_transfer_playback,
        "spotify_play": spotify_play,
        "spotify_pause": spotify_pause,
        "spotify_next": spotify_next,
        "spotify_previous": spotify_previous,
        "spotify_seek": spotify_seek,
        "spotify_set_volume": spotify_set_volume,
        "spotify_set_shuffle": spotify_set_shuffle,
        "spotify_set_repeat": spotify_set_repeat,
        "spotify_add_to_queue": spotify_add_to_queue,
        "spotify_get_queue": spotify_get_queue,
        "spotify_get_show": spotify_get_show,
        "spotify_get_show_episodes": spotify_get_show_episodes,
        "spotify_get_episode": spotify_get_episode,
        "spotify_get_markets": spotify_get_markets,
    }
    return ToolDefinition(
        name=name,
        description=desc,
        parameters={"type": "object", "properties": props, "required": required or []},
        handler=handler_map[name],
    )


_S = {"type": "string"}
_I = {"type": "integer"}
_B = {"type": "boolean"}
_N = {"type": "number"}

SPOTIFY_TOOLS = [
    # Auth
    _td("spotify_auth_status",  "Check if Spotify is authorized. Returns authorized, expired, needs_reauth.", {}),
    _td("spotify_get_auth_url", "Generate the Spotify OAuth URL. Tell the user to open it in their browser.", {}),
    # Search
    _td("spotify_search", "Search Spotify catalog for tracks, albums, artists, playlists, shows, episodes.",
        {"query": _S, "type": {"type": "string", "enum": ["track","album","artist","playlist","show","episode"], "default": "track"}, "limit": _I, "offset": _I, "market": _S}, ["query"]),
    # Tracks
    _td("spotify_get_track",         "Get a track by ID.",          {"track_id": _S, "market": _S}, ["track_id"]),
    _td("spotify_get_tracks",        "Get multiple tracks by IDs (comma-separated).", {"ids": _S}, ["ids"]),
    _td("spotify_get_audio_features","Get audio features for a track (tempo, energy, danceability, etc.).", {"track_id": _S}, ["track_id"]),
    _td("spotify_get_recommendations","Get track recommendations based on seeds.", {
        "seed_tracks": _S, "seed_artists": _S, "seed_genres": _S, "limit": _I,
        "min_energy": _N, "max_energy": _N, "min_tempo": _N, "max_tempo": _N,
        "min_valence": _N, "max_valence": _N, "min_danceability": _N, "max_danceability": _N,
    }),
    # Albums
    _td("spotify_get_album",         "Get an album by ID.", {"album_id": _S, "market": _S}, ["album_id"]),
    _td("spotify_get_album_tracks",  "Get tracks of an album.", {"album_id": _S, "limit": _I, "offset": _I, "market": _S}, ["album_id"]),
    _td("spotify_get_new_releases",  "Get new album releases.", {"country": _S, "limit": _I}),
    # Artists
    _td("spotify_get_artist",           "Get an artist by ID.", {"artist_id": _S}, ["artist_id"]),
    _td("spotify_get_artist_albums",    "Get an artist's albums.", {"artist_id": _S, "include_groups": _S, "limit": _I, "market": _S}, ["artist_id"]),
    _td("spotify_get_artist_top_tracks","Get an artist's top tracks.", {"artist_id": _S, "market": _S}, ["artist_id"]),
    _td("spotify_get_related_artists",  "Get artists related to a given artist.", {"artist_id": _S}, ["artist_id"]),
    # Playlists
    _td("spotify_get_playlist",         "Get a playlist by ID.", {"playlist_id": _S, "fields": _S, "market": _S}, ["playlist_id"]),
    _td("spotify_get_playlist_tracks",  "Get tracks in a playlist.", {"playlist_id": _S, "limit": _I, "offset": _I, "fields": _S, "market": _S}, ["playlist_id"]),
    _td("spotify_create_playlist",      "Create a new playlist for a user.", {"user_id": _S, "name": _S, "description": _S, "public": _B}, ["user_id","name"]),
    _td("spotify_add_to_playlist",      "Add tracks/episodes to a playlist (comma-separated URIs).", {"playlist_id": _S, "uris": _S, "position": _I}, ["playlist_id","uris"]),
    _td("spotify_remove_from_playlist", "Remove tracks from a playlist (comma-separated URIs).", {"playlist_id": _S, "uris": _S}, ["playlist_id","uris"]),
    _td("spotify_featured_playlists",   "Get Spotify featured playlists.", {"country": _S, "limit": _I}),
    _td("spotify_category_playlists",   "Get playlists for a category.", {"category_id": _S, "country": _S, "limit": _I}, ["category_id"]),
    _td("spotify_get_categories",       "Get browse categories.", {"country": _S, "limit": _I}),
    # User
    _td("spotify_get_current_user",   "Get the current authenticated user's profile.", {}),
    _td("spotify_get_user",           "Get a user's public profile.", {"user_id": _S}, ["user_id"]),
    _td("spotify_get_my_playlists",   "Get the current user's playlists.", {"limit": _I, "offset": _I}),
    _td("spotify_get_my_top",         "Get user's top tracks or artists.", {"type": {"type":"string","enum":["tracks","artists"]}, "time_range": {"type":"string","enum":["short_term","medium_term","long_term"]}, "limit": _I}),
    _td("spotify_get_recently_played","Get recently played tracks.", {"limit": _I}),
    # Library
    _td("spotify_get_saved_tracks",     "Get user's saved tracks.", {"limit": _I, "offset": _I, "market": _S}),
    _td("spotify_save_tracks",          "Save tracks to user's library (comma-separated IDs).", {"ids": _S}, ["ids"]),
    _td("spotify_remove_saved_tracks",  "Remove tracks from user's library.", {"ids": _S}, ["ids"]),
    _td("spotify_check_saved_tracks",   "Check if tracks are saved (comma-separated IDs).", {"ids": _S}, ["ids"]),
    _td("spotify_get_saved_albums",     "Get user's saved albums.", {"limit": _I, "offset": _I}),
    _td("spotify_save_albums",          "Save albums to user's library.", {"ids": _S}, ["ids"]),
    # Follow
    _td("spotify_follow_artist",      "Follow artists (comma-separated IDs).", {"ids": _S}, ["ids"]),
    _td("spotify_unfollow_artist",    "Unfollow artists.", {"ids": _S}, ["ids"]),
    _td("spotify_get_followed_artists","Get followed artists.", {"limit": _I}),
    _td("spotify_follow_playlist",    "Follow a playlist.", {"playlist_id": _S, "public": _B}, ["playlist_id"]),
    # Player
    _td("spotify_get_player_state",     "Get current playback state.", {"market": _S}),
    _td("spotify_get_currently_playing","Get currently playing track/episode.", {"market": _S}),
    _td("spotify_get_devices",          "Get available playback devices.", {}),
    _td("spotify_transfer_playback",    "Transfer playback to a device.", {"device_id": _S, "play": _B}, ["device_id"]),
    _td("spotify_play",                 "Start/resume playback. Provide URIs (tracks/episodes) or context_uri (album/playlist/artist).",
        {"uris": _S, "context_uri": _S, "device_id": _S, "offset": _I}),
    _td("spotify_pause",    "Pause playback.", {"device_id": _S}),
    _td("spotify_next",     "Skip to next track.", {"device_id": _S}),
    _td("spotify_previous", "Skip to previous track.", {"device_id": _S}),
    _td("spotify_seek",     "Seek to position in current track.", {"position_ms": _I, "device_id": _S}, ["position_ms"]),
    _td("spotify_set_volume","Set playback volume (0-100).", {"volume_percent": _I, "device_id": _S}, ["volume_percent"]),
    _td("spotify_set_shuffle","Enable/disable shuffle.", {"state": _B, "device_id": _S}, ["state"]),
    _td("spotify_set_repeat", "Set repeat mode: off | track | context.", {"state": {"type":"string","enum":["off","track","context"]}, "device_id": _S}, ["state"]),
    _td("spotify_add_to_queue","Add a track or episode to the queue.", {"uri": _S, "device_id": _S}, ["uri"]),
    _td("spotify_get_queue",  "Get the playback queue.", {}),
    # Shows
    _td("spotify_get_show",          "Get a podcast show by ID.", {"show_id": _S, "market": _S}, ["show_id"]),
    _td("spotify_get_show_episodes", "Get episodes of a show.", {"show_id": _S, "limit": _I, "offset": _I, "market": _S}, ["show_id"]),
    _td("spotify_get_episode",       "Get a podcast episode by ID.", {"episode_id": _S, "market": _S}, ["episode_id"]),
    # Markets
    _td("spotify_get_markets", "Get available Spotify markets.", {}),
]


SPOTIFY_SKILL = Skill(
    name="spotify",
    description="Full Spotify Web API — search, catalog, playback, queue, library, playlists, follow, recommendations, podcasts",
    tools=SPOTIFY_TOOLS,
    workflow_examples="",
    memory_seeds={
        "spotify_note": "Spotify URIs look like spotify:track:4iV5W9uYEdYUVa79Axb7Rh. Use spotify_search first to resolve names to IDs/URIs.",
    },
)
