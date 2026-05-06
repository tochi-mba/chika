# Spotify skill

Control the user's Spotify account from chat. **Connecting takes one
click** — the user opens Settings → Integrations → Connect Spotify (or
runs `chika spotify connect`), the browser pops up to Spotify's
authorize page, they click Allow, and the connection is live.

If a tool returns `{ "error": "not_authenticated" }`, the user hasn't
connected yet. Tell them to either:

- **Vue UI**: Open Settings → Integrations → click **Connect Spotify**.
- **Extension popup**: Settings page → Integrations → **Connect Spotify**.
- **CLI**: Run `chika spotify connect` (or `/spotify connect` mid-chat).

The OAuth flow is PKCE-based with a baked-in CLIENT_ID, so most users
never have to register a Spotify Developer app. Power users who want
their own app can override `CHIKA_SPOTIFY_CLIENT_ID` in the environment.

## Connection storage modes

Tokens are stored per-profile by default — every Chika profile has its
own Spotify connection at `<data_dir>/spotify/<profile>/tokens.json`.
Two opt-in variations:

| Mode | Setting | Behaviour |
|---|---|---|
| Per-profile (default) | `spotify_share_across_profiles=off` | Each profile connects to its own Spotify account. |
| Shared | `spotify_share_across_profiles=on` | Every profile reads/writes the `_shared` bucket — one account for the whole machine. |
| Shared + override | `spotify_share_across_profiles=on` AND `spotify_profile_overrides[<profile>]=true` | Most profiles share one account, but the overriding profile uses its own. |

Override resolution is per-call: when a profile is in
`spotify_profile_overrides`, the resolver returns its name (own
bucket) regardless of the global share flag. Useful for "everyone on
this laptop shares my Spotify, except the work profile uses the
team account."

The `/api/spotify/status` response surfaces all three flags so every
UI surface can render the right toggles:

```json
{
  "authorized":      true,
  "client_id_set":   true,
  "display_name":    "Tochi",
  "product":         "premium",
  "profile":         "work",
  "active_profile":  "work",
  "shared":          false,
  "shared_setting":  true,
  "overrides_share": true,
  "profile_overrides": {"work": true}
}
```

## Tools

| Tool                 | Purpose                                            |
|----------------------|----------------------------------------------------|
| `spotify_search`     | Search for tracks / albums / artists / playlists.  |
| `spotify_play`       | Play a URI or resume.                              |
| `spotify_pause`      | Pause playback.                                    |
| `spotify_next`       | Skip to next track.                                |
| `spotify_previous`   | Previous track.                                    |
| `spotify_queue`      | Add a track to the queue.                          |
| `spotify_get_playlists` | List the user's playlists.                       |
| `spotify_create_playlist` | Create a new playlist.                          |
| `spotify_save_track` | Save a track to the user's library.                |

## Pattern: search and play
```json
{"type": "sequential", "steps": [
  {"tool": "spotify_search", "args": {"query": "Floating Points Crush", "type": "track"}, "store_result_as": "$hits"},
  {"tool": "spotify_play",   "args": {"uri": "$hits.tracks[0].uri"}}
]}
```

---

## Reference patterns (migrated from workflow_examples)

### Spotify Workflows

**Play an artist's top tracks:**
```json
{"type": "sequential", "steps": [
  {"id": "search", "tool": "spotify_search",
   "args": {"query": "$artist_name", "type": "artist", "limit": 1},
   "store_result_as": "$artist_result"},
  {"id": "top", "tool": "spotify_get_artist_top_tracks",
   "args": {"artist_id": "$artist_result.artists.items[0].id"},
   "store_result_as": "$top_tracks"},
  {"id": "play", "tool": "spotify_play",
   "args": {"uris": "$top_tracks.tracks[0].uri"}}
]}
```

**Save top-5 recommendations to a new playlist:**
```json
{"type": "sequential", "steps": [
  {"id": "me",  "tool": "spotify_get_current_user", "store_result_as": "$me"},
  {"id": "recs","tool": "spotify_get_recommendations",
   "args": {"seed_genres": "pop", "limit": 5}, "store_result_as": "$recs"},
  {"id": "pl",  "tool": "spotify_create_playlist",
   "args": {"user_id": "$me.id", "name": "Chika Mix"}, "store_result_as": "$playlist"},
  {"id": "add", "tool": "spotify_add_to_playlist",
   "args": {"playlist_id": "$playlist.id", "uris": "$recs.tracks[0].uri"}}
]}
```

---

<!-- chika:tool-reference:auto-start -->

<!-- This block is auto-generated from the live tool registry by
     scripts/sync_skill_docs.py. Don't hand-edit between the
     start/end markers — your changes will be overwritten.    -->

## Tool reference

_55 tools registered with the `spotify` skill._

### `spotify_add_to_playlist`

Add tracks/episodes to a playlist (comma-separated URIs).

**Args**:

- `playlist_id` (string, **required**)
- `uris` (string, **required**)
- `position` (integer, optional)

### `spotify_add_to_queue`

Add a track or episode to the queue.

**Args**:

- `uri` (string, **required**)
- `device_id` (string, optional)

### `spotify_auth_status`

Check if Spotify is authorized. Returns authorized, expired, needs_reauth.

*No parameters.*

### `spotify_category_playlists`

Get playlists for a category.

**Args**:

- `category_id` (string, **required**)
- `country` (string, optional)
- `limit` (integer, optional)

### `spotify_check_saved_tracks`

Check if tracks are saved (comma-separated IDs).

**Args**:

- `ids` (string, **required**)

### `spotify_create_playlist`

Create a new playlist for a user.

**Args**:

- `user_id` (string, **required**)
- `name` (string, **required**)
- `description` (string, optional)
- `public` (boolean, optional)

### `spotify_featured_playlists`

Get Spotify featured playlists.

**Args**:

- `country` (string, optional)
- `limit` (integer, optional)

### `spotify_follow_artist`

Follow artists (comma-separated IDs).

**Args**:

- `ids` (string, **required**)

### `spotify_follow_playlist`

Follow a playlist.

**Args**:

- `playlist_id` (string, **required**)
- `public` (boolean, optional)

### `spotify_get_album`

Get an album by ID.

**Args**:

- `album_id` (string, **required**)
- `market` (string, optional)

### `spotify_get_album_tracks`

Get tracks of an album.

**Args**:

- `album_id` (string, **required**)
- `limit` (integer, optional)
- `offset` (integer, optional)
- `market` (string, optional)

### `spotify_get_artist`

Get an artist by ID.

**Args**:

- `artist_id` (string, **required**)

### `spotify_get_artist_albums`

Get an artist's albums.

**Args**:

- `artist_id` (string, **required**)
- `include_groups` (string, optional)
- `limit` (integer, optional)
- `market` (string, optional)

### `spotify_get_artist_top_tracks`

Get an artist's top tracks.

**Args**:

- `artist_id` (string, **required**)
- `market` (string, optional)

### `spotify_get_audio_features`

Get audio features for a track (tempo, energy, danceability, etc.).

**Args**:

- `track_id` (string, **required**)

### `spotify_get_auth_url`

Generate the Spotify OAuth URL. Tell the user to open it in their browser.

*No parameters.*

### `spotify_get_categories`

Get browse categories.

**Args**:

- `country` (string, optional)
- `limit` (integer, optional)

### `spotify_get_current_user`

Get the current authenticated user's profile.

*No parameters.*

### `spotify_get_currently_playing`

Get currently playing track/episode.

**Args**:

- `market` (string, optional)

### `spotify_get_devices`

Get available playback devices.

*No parameters.*

### `spotify_get_episode`

Get a podcast episode by ID.

**Args**:

- `episode_id` (string, **required**)
- `market` (string, optional)

### `spotify_get_followed_artists`

Get followed artists.

**Args**:

- `limit` (integer, optional)

### `spotify_get_markets`

Get available Spotify markets.

*No parameters.*

### `spotify_get_my_playlists`

Get the current user's playlists.

**Args**:

- `limit` (integer, optional)
- `offset` (integer, optional)

### `spotify_get_my_top`

Get user's top tracks or artists.

**Args**:

- `type` (string, optional)
- `time_range` (string, optional)
- `limit` (integer, optional)

### `spotify_get_new_releases`

Get new album releases.

**Args**:

- `country` (string, optional)
- `limit` (integer, optional)

### `spotify_get_player_state`

Get current playback state.

**Args**:

- `market` (string, optional)

### `spotify_get_playlist`

Get a playlist by ID.

**Args**:

- `playlist_id` (string, **required**)
- `fields` (string, optional)
- `market` (string, optional)

### `spotify_get_playlist_tracks`

Get tracks in a playlist.

**Args**:

- `playlist_id` (string, **required**)
- `limit` (integer, optional)
- `offset` (integer, optional)
- `fields` (string, optional)
- `market` (string, optional)

### `spotify_get_queue`

Get the playback queue.

*No parameters.*

### `spotify_get_recently_played`

Get recently played tracks.

**Args**:

- `limit` (integer, optional)

### `spotify_get_recommendations`

Get track recommendations based on seeds.

**Args**:

- `seed_tracks` (string, optional)
- `seed_artists` (string, optional)
- `seed_genres` (string, optional)
- `limit` (integer, optional)
- `min_energy` (number, optional)
- `max_energy` (number, optional)
- `min_tempo` (number, optional)
- `max_tempo` (number, optional)
- `min_valence` (number, optional)
- `max_valence` (number, optional)
- `min_danceability` (number, optional)
- `max_danceability` (number, optional)

### `spotify_get_related_artists`

Get artists related to a given artist.

**Args**:

- `artist_id` (string, **required**)

### `spotify_get_saved_albums`

Get user's saved albums.

**Args**:

- `limit` (integer, optional)
- `offset` (integer, optional)

### `spotify_get_saved_tracks`

Get user's saved tracks.

**Args**:

- `limit` (integer, optional)
- `offset` (integer, optional)
- `market` (string, optional)

### `spotify_get_show`

Get a podcast show by ID.

**Args**:

- `show_id` (string, **required**)
- `market` (string, optional)

### `spotify_get_show_episodes`

Get episodes of a show.

**Args**:

- `show_id` (string, **required**)
- `limit` (integer, optional)
- `offset` (integer, optional)
- `market` (string, optional)

### `spotify_get_track`

Get a track by ID.

**Args**:

- `track_id` (string, **required**)
- `market` (string, optional)

### `spotify_get_tracks`

Get multiple tracks by IDs (comma-separated).

**Args**:

- `ids` (string, **required**)

### `spotify_get_user`

Get a user's public profile.

**Args**:

- `user_id` (string, **required**)

### `spotify_next`

Skip to next track.

**Args**:

- `device_id` (string, optional)

### `spotify_pause`

Pause playback.

**Args**:

- `device_id` (string, optional)

### `spotify_play`

Start/resume playback. Provide URIs (tracks/episodes) or context_uri (album/playlist/artist).

**Args**:

- `uris` (string, optional)
- `context_uri` (string, optional)
- `device_id` (string, optional)
- `offset` (integer, optional)

### `spotify_previous`

Skip to previous track.

**Args**:

- `device_id` (string, optional)

### `spotify_remove_from_playlist`

Remove tracks from a playlist (comma-separated URIs).

**Args**:

- `playlist_id` (string, **required**)
- `uris` (string, **required**)

### `spotify_remove_saved_tracks`

Remove tracks from user's library.

**Args**:

- `ids` (string, **required**)

### `spotify_save_albums`

Save albums to user's library.

**Args**:

- `ids` (string, **required**)

### `spotify_save_tracks`

Save tracks to user's library (comma-separated IDs).

**Args**:

- `ids` (string, **required**)

### `spotify_search`

Search Spotify catalog for tracks, albums, artists, playlists, shows, episodes.

**Args**:

- `query` (string, **required**)
- `type` (string, optional)
- `limit` (integer, optional)
- `offset` (integer, optional)
- `market` (string, optional)

### `spotify_seek`

Seek to position in current track.

**Args**:

- `position_ms` (integer, **required**)
- `device_id` (string, optional)

### `spotify_set_repeat`

Set repeat mode: off | track | context.

**Args**:

- `state` (string, **required**)
- `device_id` (string, optional)

### `spotify_set_shuffle`

Enable/disable shuffle.

**Args**:

- `state` (boolean, **required**)
- `device_id` (string, optional)

### `spotify_set_volume`

Set playback volume (0-100).

**Args**:

- `volume_percent` (integer, **required**)
- `device_id` (string, optional)

### `spotify_transfer_playback`

Transfer playback to a device.

**Args**:

- `device_id` (string, **required**)
- `play` (boolean, optional)

### `spotify_unfollow_artist`

Unfollow artists.

**Args**:

- `ids` (string, **required**)

<!-- chika:tool-reference:auto-end -->
