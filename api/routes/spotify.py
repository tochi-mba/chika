from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from chika.skills.spotify_skill import oauth as spotify_oauth

router = APIRouter()


@router.get("/auth/spotify")
async def spotify_auth_start():
    if not spotify_oauth.CLIENT_ID:
        return HTMLResponse("<h2>CHIKA_SPOTIFY_CLIENT_ID not set in .env</h2>", status_code=400)
    url, _state, _verifier = spotify_oauth.build_auth_url()
    return RedirectResponse(url)


@router.get("/auth/spotify/callback")
async def spotify_auth_callback(
    code: str = Query(""), state: str = Query(""), error: str = Query("")
):
    if error:
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;background:#0d0d0f;color:#e8e8f0;padding:40px">
        <h2>Spotify authorization failed</h2><p>{error}</p>
        <a href="/" style="color:#6c63ff">Back to Chika</a>
        </body></html>""")
    result = await spotify_oauth.exchange_code(code, state)
    if "error" in result:
        return HTMLResponse(f"""
        <html><body style="font-family:sans-serif;background:#0d0d0f;color:#e8e8f0;padding:40px">
        <h2>Token exchange failed</h2><p>{result['error']}</p>
        <a href="/" style="color:#6c63ff">Back to Chika</a>
        </body></html>""")
    return HTMLResponse("""
    <html><body style="font-family:sans-serif;background:#0d0d0f;color:#e8e8f0;padding:40px;text-align:center">
    <h2>Spotify authorized successfully!</h2>
    <p style="color:#888;margin:16px 0">You can close this tab and return to Chika.</p>
    <script>setTimeout(() => window.close(), 2000)</script>
    <a href="/" style="color:#6c63ff">Back to Chika</a>
    </body></html>""")


@router.get("/auth/spotify/status")
async def spotify_auth_status_endpoint():
    status = spotify_oauth.auth_status()
    if not status["authorized"] and status.get("has_refresh"):
        await spotify_oauth.refresh_access_token()
        status = spotify_oauth.auth_status()
    if not status["authorized"]:
        try:
            url, _, _ = spotify_oauth.build_auth_url()
            status["auth_url"] = url
        except Exception:
            pass
    return status
