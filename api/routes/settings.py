from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import api.settings_store as settings_store
from api.auth import require_auth
from api.broadcast import push_to_all_frontend_sessions
from api.models import SettingsPatch

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/settings")
async def get_settings():
    return {
        **settings_store.all_settings(),
        "categories": settings_store.CATEGORIES,
    }


@router.patch("/api/settings")
async def patch_settings(body: SettingsPatch):
    patch = body.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=400, detail="No valid settings provided")
    try:
        updated = settings_store.update(patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await push_to_all_frontend_sessions({"type": "settings_update", **updated})
    return updated
