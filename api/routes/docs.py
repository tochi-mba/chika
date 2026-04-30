from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from api.readme_html import README_HTML

router = APIRouter()


@router.get("/readme", include_in_schema=False)
async def api_readme():
    """Human-readable API documentation — no auth required."""
    return HTMLResponse(README_HTML)
