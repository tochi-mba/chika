from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_auth
from api.session_manager import session_manager

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/profiles")
async def list_profiles():
    pm = session_manager._profile_manager
    return {"profiles": pm.list_profiles()}
