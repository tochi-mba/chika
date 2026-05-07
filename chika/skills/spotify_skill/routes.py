"""
Spotify HTTP routes — connection lifecycle for the UI surfaces.

Endpoints:

  GET  /api/spotify/status        — connection status + cached profile
  GET  /api/spotify/profile       — fetch + return /me (force-refresh cache)
  POST /api/spotify/connect       — kick off auth flow, opens browser
  POST /api/spotify/disconnect    — clear local tokens

  GET  /auth/spotify              — redirect to Spotify authorize URL
                                     (back-compat for in-tab flows)
  GET  /auth/spotify/callback     — Spotify's redirect lands here;
                                     exchanges code → tokens, returns
                                     a themed auto-close HTML page,
                                     broadcasts ``spotify_auth_changed``
                                     so every connected client refreshes

Design notes:

  - The browser-opening + URL-building lives in ``connection.start_connect``
    so the CLI subcommand and the HTTP route share one code path.
  - The callback emits a WS event so a Vue settings panel polling the
    status endpoint isn't necessary — clients update in real time.
  - The callback HTML uses inline CSS only (no external assets) since
    it renders before the user's tab has any auth context.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from api.broadcast import push_to_all_frontend_sessions
from chika.branding import trefoil_svg
from chika.skills.spotify_skill import connection as spotify_conn
from chika.skills.spotify_skill import oauth as spotify_oauth

router = APIRouter()


# ── JSON API: /api/spotify/* ────────────────────────────────────────────

@router.get("/api/spotify/status")
async def spotify_status() -> dict:
    """Return the current connection status (no network call)."""
    s = spotify_conn.status()
    if not s["authorized"] and s.get("has_refresh"):
        # Try a silent refresh — if the refresh succeeds, the next
        # `status()` call will return authorized=True.
        await spotify_oauth.refresh_access_token()
        s = spotify_conn.status()
    return s


@router.get("/api/spotify/profile")
async def spotify_profile() -> JSONResponse:
    """Fetch the user's Spotify profile (force-refresh cache)."""
    profile = await spotify_conn.fetch_profile(force=True)
    if profile is None:
        return JSONResponse(
            {"error": "not_authorized", "message": "Connect to Spotify first."},
            status_code=401,
        )
    return JSONResponse(profile)


@router.post("/api/spotify/connect")
async def spotify_connect(open_browser: bool = True) -> dict:
    """Begin the OAuth flow.

    Returns the authorize URL. When ``open_browser=True`` (default),
    also opens the URL in the user's default browser. Callers in
    headless contexts (extension popup, remote SSH) can pass
    ``open_browser=false`` and surface the URL themselves.
    """
    return spotify_conn.start_connect(open_browser=open_browser)


@router.post("/api/spotify/disconnect")
async def spotify_disconnect() -> dict:
    """Clear local tokens for the active profile."""
    result = await spotify_conn.disconnect()
    # Notify every open client so they swap their UI to "not connected"
    # without polling.
    await push_to_all_frontend_sessions({
        "type": "spotify_auth_changed",
        "authorized": False,
    })
    return result


# ── OAuth callback flow ─────────────────────────────────────────────────

@router.get("/auth/spotify", response_model=None)
async def spotify_auth_start() -> HTMLResponse | RedirectResponse:
    """Redirect to Spotify's authorize page.

    Used by the in-tab "Connect" flow when the frontend prefers to
    redirect rather than open a new window. The /api/spotify/connect
    JSON endpoint is the canonical path for the new UI surfaces.
    """
    if not spotify_oauth.CLIENT_ID:
        return HTMLResponse(_html_error(
            title="Spotify isn't configured",
            body=(
                "<p>The Chika Spotify CLIENT_ID isn't set on this server. "
                "Set <code>CHIKA_SPOTIFY_CLIENT_ID</code> in your "
                "environment, or paste your app's client_id into "
                "<code>chika/skills/spotify_skill/oauth.py</code>.</p>"
            ),
        ), status_code=400)
    url, _state, _verifier = spotify_oauth.build_auth_url()
    return RedirectResponse(url)


@router.get("/auth/spotify/callback")
async def spotify_auth_callback(
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
) -> HTMLResponse:
    """Spotify's redirect_uri target. Renders an auto-close HTML page."""
    if error:
        # User clicked "Cancel" on Spotify's authorize page, or the
        # request was malformed.
        await push_to_all_frontend_sessions({
            "type": "spotify_auth_changed",
            "authorized": False,
            "error": error,
        })
        return HTMLResponse(_html_error(
            title="Connection cancelled",
            body=(
                f"<p>Spotify said: <code>{_safe(error)}</code></p>"
                f"<p class='hint'>You can close this tab and try again from "
                f"Chika settings.</p>"
            ),
        ))

    if not code:
        return HTMLResponse(_html_error(
            title="Missing authorization code",
            body=(
                "<p>The callback URL was hit without an auth code. This usually "
                "means the redirect URI registered in your Spotify app dashboard "
                "doesn't match the one Chika is using.</p>"
            ),
        ))

    result = await spotify_oauth.exchange_code(code, state)
    if "error" in result:
        await push_to_all_frontend_sessions({
            "type": "spotify_auth_changed",
            "authorized": False,
            "error": result.get("error", "unknown"),
        })
        return HTMLResponse(_html_error(
            title="Token exchange failed",
            body=(
                f"<p><strong>{_safe(result.get('error', ''))}</strong></p>"
                f"<p>{_safe(result.get('message', ''))}</p>"
            ),
        ))

    # Fetch the /me profile so the UI can render "Connected as X" without
    # waiting for the next polling tick.
    profile = await spotify_conn.fetch_profile(force=True)
    name = profile.get("display_name", "") if profile else ""

    await push_to_all_frontend_sessions({
        "type":         "spotify_auth_changed",
        "authorized":   True,
        "display_name": name,
        "product":      profile.get("product", "") if profile else "",
    })

    return HTMLResponse(_html_success(name))


# ── HTML templates ──────────────────────────────────────────────────────
#
# Inline-only — these pages render in the user's browser before any
# Chika static assets are loaded, so we can't rely on stylesheets or
# fonts from the app bundle. The trefoil markup comes from
# ``chika.branding.trefoil_svg`` (single Python-side source of truth);
# the cross-surface duplication is governed by ADR-27 +
# ``scripts/check_brand_parity.py``.

_BASE_STYLE = """
  :root {
    --bg: #0e0e14; --surface: #161620; --border: rgba(255,255,255,0.08);
    --text: #ededf2; --muted: #a8a8b8; --accent: #6c63ff; --accent-2: #7c70ff;
    --success: #3dd68c; --error: #e05c5c;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; min-height: 100vh; }
  body {
    font-family: -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
    background: radial-gradient(800px 500px at 50% -100px,
      color-mix(in srgb, var(--accent) 8%, transparent), transparent 60%),
      var(--bg);
    color: var(--text);
    display: grid; place-items: center;
    -webkit-font-smoothing: antialiased;
  }
  .card {
    width: min(440px, 92vw);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: 40px 36px 32px;
    text-align: center;
    box-shadow: 0 20px 60px rgba(0,0,0,0.32);
  }
  .mark { display: grid; place-items: center; margin-bottom: 24px; }
  h1 {
    font-size: 22px; font-weight: 600;
    letter-spacing: -0.02em; margin: 0 0 10px;
  }
  p { margin: 0 0 12px; color: var(--muted); line-height: 1.55; }
  p code {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 12.5px;
    background: rgba(108,99,255,0.10); color: var(--accent);
    padding: 2px 6px; border-radius: 4px;
  }
  .hint { font-size: 12.5px; color: var(--muted); opacity: 0.8; margin-top: 18px; }
  .pill {
    display: inline-block;
    margin-top: 18px;
    padding: 6px 14px; border-radius: 999px;
    font-size: 12px; font-weight: 500;
    background: color-mix(in srgb, var(--success) 14%, transparent);
    color: var(--success);
    letter-spacing: 0.02em;
  }
  .pill.err {
    background: color-mix(in srgb, var(--error) 14%, transparent);
    color: var(--error);
  }
"""


def _safe(s: str) -> str:
    """Minimal HTML escape for the error templates. Keep small — these
    pages have no user-supplied HTML beyond Spotify error codes."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _html_success(display_name: str) -> str:
    name_html = (
        f"<p>Welcome back, <strong>{_safe(display_name)}</strong>.</p>"
        if display_name else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="utf-8"><title>Chika — Spotify Connected</title>
  <style>{_BASE_STYLE}</style>
</head><body>
  <div class="card">
    <div class="mark">{trefoil_svg(size=48)}</div>
    <h1>Spotify connected</h1>
    {name_html}
    <p>Chika can now control your music. You can close this tab.</p>
    <span class="pill">✓ Connected</span>
    <p class="hint">This tab will close in a moment.</p>
  </div>
  <script>setTimeout(() => window.close(), 2500);</script>
</body></html>"""


def _html_error(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
  <meta charset="utf-8"><title>Chika — Spotify</title>
  <style>{_BASE_STYLE}</style>
</head><body>
  <div class="card">
    <div class="mark">{trefoil_svg(size=48)}</div>
    <h1>{_safe(title)}</h1>
    {body}
    <span class="pill err">Connection not completed</span>
    <p class="hint">You can close this tab and try again from Chika settings.</p>
  </div>
</body></html>"""
