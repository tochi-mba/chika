from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_auth
from chika.skills.browser_skill.extension_manager import extension_manager

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/extension/status")
async def extension_status():
    return {
        "connected":   extension_manager.connected,
        "watch_count": extension_manager.watch_count(),
    }
