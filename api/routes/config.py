from __future__ import annotations

from fastapi import APIRouter, Depends

import config
from api.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/config")
async def get_public_config():
    cfg = config.get_provider_config()
    return {
        "provider":           cfg.provider,
        "model":              cfg.model,
        "max_history_tokens": config.MAX_HISTORY_TOKENS,
        "max_tool_turns":     config.MAX_TOOL_TURNS,
        "auth_enabled":       bool(config.CHIKA_API_KEY),
    }
