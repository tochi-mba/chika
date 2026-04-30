from __future__ import annotations

from fastapi import APIRouter

import config

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "provider": config.PROVIDER, "model": config.get_provider_config().model}
