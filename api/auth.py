"""FastAPI dependency — bearer-token auth."""
from __future__ import annotations

from fastapi import Header, HTTPException

import config


async def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Raise 401 when CHIKA_API_KEY is set and the Authorization header doesn't match."""
    required = config.CHIKA_API_KEY
    if not required:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if authorization[len("Bearer "):] != required:
        raise HTTPException(status_code=401, detail="Invalid API key")
