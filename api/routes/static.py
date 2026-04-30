from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

_PLACEHOLDER_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Chika — Build required</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #0a0a0a; color: #e5e5e5; display: flex;
           align-items: center; justify-content: center; min-height: 100vh; }
    .card { background: #141414; border: 1px solid #262626; border-radius: 12px;
            padding: 40px 48px; max-width: 520px; width: 100%; }
    h1 { font-size: 22px; font-weight: 600; color: #fff; margin-bottom: 8px; }
    p  { color: #888; font-size: 14px; line-height: 1.6; margin-bottom: 24px; }
    .step { background: #0a0a0a; border: 1px solid #262626; border-radius: 8px;
            padding: 16px 20px; margin-bottom: 12px; }
    .step code { font-family: 'SF Mono', Consolas, monospace; font-size: 13px;
                 color: #7dd3fc; display: block; margin-top: 6px; }
    .step span { font-size: 12px; color: #555; }
    .alt { margin-top: 24px; padding-top: 24px; border-top: 1px solid #262626; }
    .alt p { margin-bottom: 0; }
    a { color: #7dd3fc; text-decoration: none; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Frontend not built yet</h1>
    <p>The server is running but the Vue frontend hasn't been compiled. Build it once:</p>
    <div class="step">
      <span>1. Install Node dependencies</span>
      <code>cd frontend &amp;&amp; npm install</code>
    </div>
    <div class="step">
      <span>2. Build</span>
      <code>npm run build</code>
    </div>
    <div class="step">
      <span>3. Restart the server</span>
      <code>python api/server.py</code>
    </div>
    <div class="alt">
      <p>No Node.js? Use the CLI: <code style="display:inline;color:#7dd3fc">chika</code>
      or <code style="display:inline;color:#7dd3fc">python chika.py</code></p>
    </div>
  </div>
</body>
</html>"""


def mount(app: FastAPI) -> None:
    """Mount the built frontend or a build-required placeholder."""
    if _FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def frontend_not_built():
            return HTMLResponse(_PLACEHOLDER_HTML)
