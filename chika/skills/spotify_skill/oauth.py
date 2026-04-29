"""
Spotify OAuth PKCE flow — handled server-side so the agent can trigger it.

Flow:
  1. Agent calls spotify_auth_status → sees "not_authorized"
  2. Agent calls spotify_get_auth_url → gets URL + opens it in browser if possible
  3. User visits the URL, logs into Spotify, authorizes Chika
  4. Spotify redirects to /auth/spotify/callback?code=...
  5. Callback exchanges code for tokens, saves to .env / memory
  6. Agent calls spotify_auth_status again → "authorized"
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from pathlib import Path

import httpx

CLIENT_ID       = os.getenv("CHIKA_SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET   = os.getenv("CHIKA_SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI    = os.getenv("CHIKA_SPOTIFY_REDIRECT_URI", "http://localhost:8000/auth/spotify/callback")

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

# In-memory token storage (lives for the duration of the process)
_tokens: dict[str, str] = {
    "access_token":  os.getenv("CHIKA_SPOTIFY_ACCESS_TOKEN", ""),
    "refresh_token": os.getenv("CHIKA_SPOTIFY_REFRESH_TOKEN", ""),
    "expires_at":    "0",
}
# PKCE state
_pkce_state: dict[str, str] = {}


def _gen_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _gen_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_auth_url() -> tuple[str, str, str]:
    """Returns (url, state, code_verifier)."""
    verifier  = _gen_code_verifier()
    challenge = _gen_code_challenge(verifier)
    state     = secrets.token_urlsafe(16)
    _pkce_state[state] = verifier

    params = "&".join([
        f"client_id={CLIENT_ID}",
        "response_type=code",
        f"redirect_uri={REDIRECT_URI}",
        f"scope={_SCOPES.replace(' ', '%20')}",
        f"state={state}",
        "code_challenge_method=S256",
        f"code_challenge={challenge}",
    ])
    url = f"https://accounts.spotify.com/authorize?{params}"
    return url, state, verifier


async def exchange_code(code: str, state: str) -> dict:
    """Exchange auth code for tokens. Called by the OAuth callback endpoint."""
    verifier = _pkce_state.pop(state, "")
    if not verifier:
        return {"error": "Unknown OAuth state"}

    async with httpx.AsyncClient() as client:
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
    data = r.json()
    if "error" in data:
        return data

    _tokens["access_token"]  = data.get("access_token", "")
    _tokens["refresh_token"] = data.get("refresh_token", _tokens["refresh_token"])
    _tokens["expires_at"]    = str(int(time.time()) + data.get("expires_in", 3600))

    # Persist to .env so they survive restarts
    _update_env_file()

    return {"ok": True, "scope": data.get("scope", "")}


async def refresh_access_token() -> str:
    """Refresh the access token using the refresh token."""
    rt = _tokens.get("refresh_token", "")
    if not rt:
        return ""

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type":    "refresh_token",
                "refresh_token": rt,
                "client_id":     CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    data = r.json()
    token = data.get("access_token", "")
    if token:
        _tokens["access_token"] = token
        _tokens["expires_at"]   = str(int(time.time()) + data.get("expires_in", 3600))
        if "refresh_token" in data:
            _tokens["refresh_token"] = data["refresh_token"]
        _update_env_file()
    return token


async def get_valid_access_token() -> str:
    """Returns a valid access token, refreshing if needed."""
    exp = int(_tokens.get("expires_at", "0"))
    if exp and time.time() < exp - 60:
        return _tokens["access_token"]
    if _tokens.get("refresh_token"):
        return await refresh_access_token()
    return _tokens.get("access_token", "")


def auth_status() -> dict:
    has_access  = bool(_tokens.get("access_token"))
    has_refresh = bool(_tokens.get("refresh_token"))
    exp         = int(_tokens.get("expires_at", "0"))
    expired     = exp > 0 and time.time() > exp
    return {
        "authorized":    has_access and not expired,
        "has_refresh":   has_refresh,
        "expired":       expired,
        "expires_at":    exp,
        "needs_reauth":  not has_access and not has_refresh,
        "auth_url_hint": f"Visit {REDIRECT_URI.rsplit('/callback')[0].replace('/callback', '')} to authorize" if not has_access else "",
    }


def _update_env_file() -> None:
    """Write tokens back to .env file so they persist across restarts."""
    env_path = Path(__file__).parents[4] / ".env"
    if not env_path.exists():
        return
    text = env_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_vals = {
        "CHIKA_SPOTIFY_ACCESS_TOKEN":  _tokens["access_token"],
        "CHIKA_SPOTIFY_REFRESH_TOKEN": _tokens["refresh_token"],
    }
    result = []
    for line in lines:
        key = line.split("=")[0] if "=" in line else ""
        if key in new_vals:
            result.append(f"{key}={new_vals.pop(key)}")
        else:
            result.append(line)
    for k, v in new_vals.items():
        result.append(f"{k}={v}")
    env_path.write_text("\n".join(result) + "\n", encoding="utf-8")
