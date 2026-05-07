"""
Spotify OAuth — handled inside Chika so non-tech users can connect
with ONE click.

Design:

  - **Baked-in CLIENT_ID with env override.** A default Chika app
    CLIENT_ID is embedded so users don't have to register their own
    Spotify Developer app. PKCE (RFC 7636) doesn't require a
    CLIENT_SECRET, so embedding the public ID is safe.
    ``CHIKA_SPOTIFY_CLIENT_ID`` overrides if a user wants their own
    app.

  - **Per-profile token storage.** Each profile gets its own
    ``<data_dir>/spotify/<profile>/tokens.json`` so a "work" profile
    and a "personal" profile can connect to different Spotify
    accounts. Atomic writes via ``chika.core._io.atomic_write``.

  - **Concurrent-refresh lock.** A per-profile ``asyncio.Lock``
    prevents two parallel ``spotify_*`` calls from both refreshing
    a stale token and one losing its old refresh token to Spotify's
    rotating-refresh policy.

  - **Log redaction.** Tokens never surface in logs — ``redact()``
    substitutes ``"<redacted>"``. ``auth_status()`` only ever returns
    a 6-char preview, never the full token, never the refresh token.

  - **Multiple redirect URIs.** ``http://127.0.0.1:8000/auth/spotify/
    callback`` AND ``http://localhost:8000/...`` should both be
    registered in the Spotify dashboard; the env override picks one.

Connection flow:

  1. User clicks "Connect Spotify" in Settings (Vue, extension, or
     CLI ``chika spotify connect``).
  2. Frontend POSTs ``/api/spotify/connect`` → server returns the
     authorize URL + opens it in the user's default browser.
  3. User authorizes on accounts.spotify.com → Spotify redirects to
     ``/auth/spotify/callback``.
  4. The callback exchanges code → tokens, persists per-profile,
     emits ``spotify_auth_changed`` over the WS so every open Chika
     surface refreshes live.
  5. Browser tab shows a themed "Connected!" page that auto-closes.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from chika.core._io import atomic_write

if TYPE_CHECKING:
    from typing import Any

log = logging.getLogger(__name__)


# ── CLIENT_ID — baked default, env-overridable ──────────────────────────
#
# The default below is the Chika public desktop app's client_id. It's
# safe to embed because PKCE flow (RFC 7636) doesn't require a
# client_secret — the per-session code_verifier proves the original
# requester. Users who want their own Spotify app for any reason can
# set ``CHIKA_SPOTIFY_CLIENT_ID`` in their environment to override.
#
# When you (the maintainer) register the Chika app at
# https://developer.spotify.com/dashboard, paste the CLIENT_ID below
# and add these redirect URIs in the dashboard:
#   http://127.0.0.1:8000/auth/spotify/callback
#   http://localhost:8000/auth/spotify/callback
_DEFAULT_CLIENT_ID = ""    # ← TODO: paste Chika app's public client_id here

CLIENT_ID: str = os.getenv("CHIKA_SPOTIFY_CLIENT_ID", _DEFAULT_CLIENT_ID)
REDIRECT_URI: str = os.getenv(
    "CHIKA_SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8000/auth/spotify/callback",
)


def reload_from_env() -> None:
    """Re-read CHIKA_SPOTIFY_CLIENT_ID + REDIRECT_URI from the env.

    Hot-reload entry point — call after a path that mutates the
    .env file (the inline Client ID input in the Settings UI, the
    /api/env PATCH endpoint, etc.) so the very next OAuth flow
    sees the new credentials without a process restart.

    The Settings UI calls this implicitly via the env router's
    ``_hot_reload_clients`` hook; manual callers (tests, CLI flows)
    invoke it directly.
    """
    global CLIENT_ID, REDIRECT_URI
    CLIENT_ID = os.getenv("CHIKA_SPOTIFY_CLIENT_ID", _DEFAULT_CLIENT_ID)
    REDIRECT_URI = os.getenv(
        "CHIKA_SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8000/auth/spotify/callback",
    )


_SCOPES = " ".join([
    "user-read-private", "user-read-email",
    "user-read-playback-state", "user-modify-playback-state",
    "user-read-currently-playing", "user-read-recently-played",
    "user-library-read", "user-library-modify",
    "user-top-read", "user-follow-read", "user-follow-modify",
    "playlist-read-private", "playlist-read-collaborative",
    "playlist-modify-public", "playlist-modify-private",
    "streaming",
])


# ── Per-profile token store ─────────────────────────────────────────────
#
# Tokens persist to ``<data_dir>/spotify/<profile>/tokens.json``. The
# data dir resolves the same way as ``api/settings_store.py`` —
# CHIKA_DATA_DIR env var when set, ``data/`` relative to repo root
# otherwise. Active profile name comes from the engine; if unset we
# bucket under ``default``.

def _data_dir() -> Path:
    explicit = os.environ.get("CHIKA_DATA_DIR")
    if explicit:
        return Path(explicit)
    # Walk up from this file: chika/skills/spotify_skill/oauth.py
    # → repo_root/data
    return Path(__file__).resolve().parents[3] / "data"


def _share_across_profiles() -> bool:
    """Whether the global setting opts every profile into one shared
    Spotify connection. Default off — per-profile is more private and
    matches user expectations ("my work profile shouldn't see my
    personal listening")."""
    try:
        from api import settings_store
        return settings_store.get(
            "spotify_share_across_profiles", "off"
        ) == "on"
    except Exception:
        return False


def _profile_overrides_share() -> bool:
    """Whether the active profile has explicitly opted out of the
    shared bucket. Only meaningful when global sharing is on."""
    try:
        from api import settings_store
        overrides = settings_store.get("spotify_profile_overrides", {}) or {}
    except Exception:
        return False
    return bool(overrides.get(_active_profile_name(), False))


def _active_profile_name() -> str:
    """Active profile from the running engine, or 'default'.

    Used as the override-key. Kept separate from _profile_name() so
    override resolution can ask "what profile am I running?" without
    re-entering the share / override decision tree.
    """
    try:
        # Lazy import — engine module is heavy and we don't want this
        # OAuth module to pull in the LLM client just to know a path.
        from api.server import engine  # type: ignore[attr-defined]
        if engine and engine._active_profile and engine._active_profile.name:
            return str(engine._active_profile.name)
    except Exception:
        pass
    return "default"


def _profile_name() -> str:
    """Resolve the storage bucket for tokens.

    Resolution order (highest precedence first):

      1. **Per-profile override** — if the active profile is flagged in
         ``spotify_profile_overrides``, use its own bucket regardless
         of the global share flag. Lets a single profile keep its own
         Spotify even when the rest of the machine shares one.
      2. **Global share** — if ``spotify_share_across_profiles`` is on,
         every profile (without an override) reads ``_shared``.
      3. **Per-profile (default)** — each profile gets its own bucket.
    """
    if _share_across_profiles() and not _profile_overrides_share():
        return "_shared"
    return _active_profile_name()


def _tokens_path(profile: str | None = None) -> Path:
    return _data_dir() / "spotify" / (profile or _profile_name()) / "tokens.json"


def _empty_tokens() -> dict[str, Any]:
    return {
        "access_token":  "",
        "refresh_token": "",
        "expires_at":    0,
        "scope":         "",
        "obtained_at":   0,
    }


# In-memory cache, keyed by profile name. Avoids reading the JSON file
# on every API call but stays consistent with the on-disk source of
# truth via the load/save helpers.
_cache: dict[str, dict[str, Any]] = {}


def _load(profile: str | None = None) -> dict[str, Any]:
    p = profile or _profile_name()
    if p in _cache:
        return _cache[p]

    path = _tokens_path(p)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tokens = {**_empty_tokens(), **data}
        except Exception as exc:
            log.warning("spotify: tokens file corrupt for %s: %s", p, exc)
            tokens = _empty_tokens()
    else:
        tokens = _empty_tokens()

    _cache[p] = tokens
    return tokens


def _save(tokens: dict[str, Any], profile: str | None = None) -> None:
    p = profile or _profile_name()
    _cache[p] = tokens
    path = _tokens_path(p)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(tokens, indent=2))


def clear_tokens(profile: str | None = None) -> None:
    """Disconnect: remove tokens for a profile (or the active one)."""
    p = profile or _profile_name()
    _cache.pop(p, None)
    path = _tokens_path(p)
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        log.warning("spotify: clear_tokens couldn't unlink %s: %s", path, exc)


def redact(value: str | None) -> str:
    """Replace any non-empty token-like string with a stable placeholder."""
    return "<redacted>" if value else ""


# ── PKCE state — persisted to disk so the CLI → server hand-off works ──
#
# State → code_verifier mapping. State is the CSRF token Spotify echoes
# back; verifier is the secret we send when exchanging the code.
#
# This used to be in-memory only, which broke ``chika spotify connect``:
# the CLI process generates the state, opens the browser, exits — the
# OAuth callback hits the SERVER process, which has its own (empty)
# in-memory dict. State lookup fails → "Auth state expired or unknown".
#
# Persisting to ``<data_dir>/spotify/_pending_states.json`` lets the
# CLI process write the state and the server process read it back.
# Entries older than ``_PKCE_TTL_SEC`` (10 min) are pruned on every
# read so a user who walks away mid-flow doesn't leak verifiers
# forever. The file is atomic-write + best-effort under concurrent
# writers — the worst case is a single state being lost, which the
# user can recover from with a fresh ``chika spotify connect``.
_pkce_state: dict[str, tuple[str, float]] = {}
_PKCE_TTL_SEC = 600


def _pending_states_path() -> Path:
    return _data_dir() / "spotify" / "_pending_states.json"


def _load_pending_states() -> dict[str, tuple[str, float]]:
    """Read pending PKCE states from disk. Returns ``{}`` on any error
    so a corrupted/missing file just means "no pending auth flows."""
    path = _pending_states_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, tuple[str, float]] = {}
    for state, payload in raw.items():
        if not isinstance(state, str):
            continue
        if not isinstance(payload, list) or len(payload) != 2:
            continue
        verifier, ts = payload
        if isinstance(verifier, str) and isinstance(ts, (int, float)):
            out[state] = (verifier, float(ts))
    return out


def _save_pending_states(states: dict[str, tuple[str, float]]) -> None:
    """Atomic-write the pending states. Best-effort; failures are
    swallowed to avoid breaking auth on a transient FS hiccup."""
    path = _pending_states_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps({k: list(v) for k, v in states.items()}))
    except Exception as exc:
        log.warning("spotify: _save_pending_states failed: %s", exc)


def _gen_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _gen_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _merge_pending_from_disk() -> None:
    """Bring the in-memory ``_pkce_state`` up to date with the on-disk
    file so the server process sees state written by the CLI process."""
    for state, payload in _load_pending_states().items():
        if state not in _pkce_state:
            _pkce_state[state] = payload


def _prune_pkce() -> None:
    """Drop expired entries from BOTH the in-memory dict and the disk
    file. Pulls fresh state from disk first so cross-process writers
    don't lose entries on prune."""
    _merge_pending_from_disk()
    cutoff = time.time() - _PKCE_TTL_SEC
    for state, (_, ts) in list(_pkce_state.items()):
        if ts < cutoff:
            _pkce_state.pop(state, None)


def build_auth_url() -> tuple[str, str, str]:
    """Build the Spotify authorize URL.

    Returns ``(url, state, code_verifier)``. Caller usually only needs
    ``url`` — state + verifier are stashed internally for the callback
    to consume.
    """
    if not CLIENT_ID:
        raise RuntimeError(
            "spotify: no client_id configured. Set CHIKA_SPOTIFY_CLIENT_ID "
            "or paste the Chika app's client_id into oauth.py's "
            "_DEFAULT_CLIENT_ID."
        )

    _prune_pkce()
    verifier  = _gen_code_verifier()
    challenge = _gen_code_challenge(verifier)
    state     = secrets.token_urlsafe(16)
    _pkce_state[state] = (verifier, time.time())
    # Persist so the server process can verify the state Spotify
    # echoes back, even when ``build_auth_url`` ran inside a
    # short-lived CLI process that's already exited.
    _save_pending_states(_pkce_state)

    params = "&".join([
        f"client_id={CLIENT_ID}",
        "response_type=code",
        f"redirect_uri={REDIRECT_URI}",
        f"scope={_SCOPES.replace(' ', '%20')}",
        f"state={state}",
        "code_challenge_method=S256",
        f"code_challenge={challenge}",
    ])
    return f"https://accounts.spotify.com/authorize?{params}", state, verifier


# ── Token exchange + refresh ────────────────────────────────────────────

# One lock per profile so concurrent refresh attempts don't both fire
# the refresh endpoint and one loses its old refresh_token to Spotify's
# rotating-refresh policy.
_refresh_locks: dict[str, asyncio.Lock] = {}


def _lock(profile: str | None = None) -> asyncio.Lock:
    p = profile or _profile_name()
    if p not in _refresh_locks:
        _refresh_locks[p] = asyncio.Lock()
    return _refresh_locks[p]


async def exchange_code(code: str, state: str) -> dict[str, Any]:
    """Exchange the authorization code for tokens. Called by callback."""
    # ``_prune_pkce`` already merges from disk, so the server process
    # picks up states written by the CLI process before pop.
    _prune_pkce()
    pair = _pkce_state.pop(state, None)
    if not pair:
        # Diagnostic context — helps the user/dev understand WHY the
        # state was unknown (process boundary? expired? wrong file?).
        path = _pending_states_path()
        on_disk = _load_pending_states()
        log.warning(
            "spotify.exchange_code: unknown state %r. "
            "in-memory keys: %s. on-disk file: %s (exists=%s, %d entries).",
            state[:8] + "…",
            sorted(s[:8] + "…" for s in _pkce_state.keys())[:5],
            path, path.is_file(), len(on_disk),
        )
        msg = (
            "Auth state expired or unknown — try connecting again."
        )
        if not path.is_file():
            msg += (
                " (Diagnostic: no pending-state file at "
                f"{path} — the chika server may be running an older "
                "version without the disk-persistence fix. Restart the "
                "server and re-run `chika spotify connect`.)"
            )
        elif not on_disk:
            msg += (
                f" (Diagnostic: pending-state file at {path} is empty — "
                "the CLI may be writing to a different data dir. "
                "Check CHIKA_DATA_DIR is consistent across CLI and server.)"
            )
        else:
            msg += (
                f" (Diagnostic: pending-state file has {len(on_disk)} "
                f"entries but state {state[:8]}… isn't one of them. "
                "Likely the auth flow took >10 min or the state on Spotify's "
                "redirect was mangled. Re-run `chika spotify connect`.)"
            )
        return {"error": "unknown_state", "message": msg}
    # Persist the post-pop state so a re-emitted callback (e.g. user
    # double-clicked the success page) can't re-consume the same
    # state and so other concurrent flows aren't replayed.
    _save_pending_states(_pkce_state)
    verifier, _ = pair

    if not CLIENT_ID:
        return {"error": "missing_client_id", "message": "Spotify CLIENT_ID not configured."}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "redirect_uri":  REDIRECT_URI,
                    "client_id":     CLIENT_ID,
                    "code_verifier": verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        log.warning("spotify: token exchange network error: %s", exc)
        return {"error": "network", "message": str(exc)}

    if r.status_code >= 400:
        # Spotify's error JSON is {"error": "...", "error_description": "..."}.
        try:
            data = r.json()
        except Exception:
            data = {}
        return {
            "error": data.get("error") or f"http_{r.status_code}",
            "message": data.get("error_description") or r.text[:200],
        }

    data = r.json()
    if "access_token" not in data:
        return {"error": "no_access_token", "message": "Spotify returned no access_token"}

    tokens = _load()
    tokens["access_token"]  = data["access_token"]
    tokens["refresh_token"] = data.get("refresh_token", tokens.get("refresh_token", ""))
    tokens["expires_at"]    = int(time.time()) + int(data.get("expires_in", 3600))
    tokens["scope"]         = data.get("scope", "")
    tokens["obtained_at"]   = int(time.time())
    _save(tokens)
    return {"ok": True, "scope": tokens["scope"]}


async def refresh_access_token(profile: str | None = None) -> str:
    """Refresh the access token using the stored refresh token.

    Returns the fresh access_token, or empty string on failure. Safe
    against concurrent calls — held under a per-profile lock so only
    one HTTP refresh is in flight at a time.
    """
    p = profile or _profile_name()
    async with _lock(p):
        tokens = _load(p)
        rt = tokens.get("refresh_token", "")
        if not rt:
            return ""

        # Re-check after acquiring the lock — another caller may have
        # already refreshed while we were queued.
        if tokens.get("access_token") and int(tokens.get("expires_at", 0)) > time.time() + 60:
            return tokens["access_token"]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    "https://accounts.spotify.com/api/token",
                    data={
                        "grant_type":    "refresh_token",
                        "refresh_token": rt,
                        "client_id":     CLIENT_ID,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.HTTPError as exc:
            log.warning("spotify: refresh network error: %s", exc)
            return ""

        if r.status_code >= 400:
            log.warning("spotify: refresh failed http %s", r.status_code)
            # 400 invalid_grant means the refresh token was revoked
            # (user changed password / revoked app access). Wipe it
            # so the next call surfaces "needs_reauth" cleanly.
            try:
                if r.json().get("error") == "invalid_grant":
                    tokens["refresh_token"] = ""
                    tokens["access_token"]  = ""
                    tokens["expires_at"]    = 0
                    _save(tokens, p)
            except Exception:
                pass
            return ""

        data = r.json()
        token = data.get("access_token", "")
        if token:
            tokens["access_token"] = token
            tokens["expires_at"]   = int(time.time()) + int(data.get("expires_in", 3600))
            # Spotify rotates refresh tokens — always store the new one
            # if returned, otherwise keep the existing.
            if data.get("refresh_token"):
                tokens["refresh_token"] = data["refresh_token"]
            tokens["obtained_at"]   = int(time.time())
            _save(tokens, p)
        return token


async def get_valid_access_token() -> str:
    """Return a non-stale access token, refreshing if needed."""
    tokens = _load()
    exp = int(tokens.get("expires_at", 0))
    # 60 s safety margin so the token doesn't expire mid-request.
    if tokens.get("access_token") and exp > time.time() + 60:
        return tokens["access_token"]
    if tokens.get("refresh_token"):
        return await refresh_access_token()
    return tokens.get("access_token", "")


def auth_status(profile: str | None = None) -> dict[str, Any]:
    """Connection status for a profile.

    Includes a redacted preview of the access token (first 6 chars +
    "…") so debug surfaces can show *something* without leaking the
    full secret. Never includes the refresh token.
    """
    tokens = _load(profile)
    has_access  = bool(tokens.get("access_token"))
    has_refresh = bool(tokens.get("refresh_token"))
    exp         = int(tokens.get("expires_at", 0))
    expired     = exp > 0 and time.time() > exp
    share_on = _share_across_profiles()
    overridden = _profile_overrides_share()
    # Surface the FULL overrides dict so the UI can mutate one entry
    # without clobbering the others. We don't include token values
    # — only the boolean flags — so this is safe to broadcast.
    try:
        from api import settings_store
        all_overrides = dict(settings_store.get("spotify_profile_overrides", {}) or {})
    except Exception:
        all_overrides = {}
    return {
        "authorized":     has_access and not expired,
        "has_refresh":    has_refresh,
        "expired":        expired,
        "expires_at":     exp,
        "obtained_at":    int(tokens.get("obtained_at", 0)),
        "scope":          tokens.get("scope", ""),
        "needs_reauth":   not has_access and not has_refresh,
        "client_id_set":  bool(CLIENT_ID),
        "profile":        profile or _profile_name(),
        "active_profile": _active_profile_name(),
        # ``shared`` is True iff the resolved bucket is ``_shared`` —
        # which means global share is on AND this profile didn't
        # override.
        "shared":         share_on and not overridden,
        # ``shared_setting`` is the global flag value (regardless of
        # whether this profile is overriding) — the UI uses it to
        # decide whether to show the override toggle at all.
        "shared_setting": share_on,
        "overrides_share": overridden,
        # Full {profile: True} dict so the UI can edit one key
        # without clobbering siblings.
        "profile_overrides": all_overrides,
        "token_preview":  (tokens.get("access_token", "")[:6] + "…") if has_access else "",
    }
