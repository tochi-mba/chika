"""``/api/env`` and ``/api/provider`` — view and edit ``.env`` from the UI.

Sensitive values (API keys, tokens, passwords) are masked by default. Pass
``?show_secrets=1`` to reveal them — the same gate is required to switch
provider via the UI so a misconfiguration can be diagnosed.

The CLI talks to the same surface via :mod:`chika._cli.env_file`; both share
:func:`chika._cli.env_file.write_env` so changes are atomic and survive
crashes.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import config
from api.auth import require_auth
from chika._cli import env_file

router = APIRouter(dependencies=[Depends(require_auth)])

_VALID_PROVIDERS = ("anthropic", "openai", "azure", "ollama")
_PROVIDER_MODEL_VAR = {
    "anthropic": "ANTHROPIC_MODEL",
    "openai":    "OPENAI_MODEL",
    "azure":     "AZURE_OPENAI_DEPLOYMENT",
    "ollama":    "OLLAMA_MODEL",
}


class EnvUpdate(BaseModel):
    set:    dict[str, str] | None = None
    unset:  list[str] | None = None


class ProviderUpdate(BaseModel):
    provider: str | None = None
    model:    str | None = None


# ── /api/env ─────────────────────────────────────────────────────────────


@router.get("/api/env")
async def get_env(show_secrets: bool = False) -> dict[str, Any]:
    """Return all ``.env`` keys. Secrets masked unless ``show_secrets=1``."""
    rows = env_file.read_env_for_display(mask_secrets=not show_secrets)
    return {
        "path": str(env_file.env_path()),
        "vars": [
            {"key": k, "value": v, "is_secret": secret}
            for k, v, secret in rows
        ],
    }


@router.patch("/api/env")
async def patch_env(body: EnvUpdate) -> dict[str, Any]:
    """Set or unset .env keys. ``set`` writes new values; ``unset`` removes
    keys. Both run through :func:`env_file.write_env` atomically.
    """
    set_map = body.set or {}
    unset = body.unset or []
    if not set_map and not unset:
        raise HTTPException(status_code=400, detail="No changes provided")

    updates: dict[str, str | None] = {}
    for k, v in set_map.items():
        if not isinstance(k, str) or not k:
            raise HTTPException(status_code=422, detail=f"Invalid key: {k!r}")
        updates[k] = str(v)
    for k in unset:
        if not isinstance(k, str) or not k:
            raise HTTPException(status_code=422, detail=f"Invalid key: {k!r}")
        updates[k] = None

    try:
        env_file.write_env(updates)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write .env: {exc}") from exc

    rows = env_file.read_env_for_display(mask_secrets=True)
    return {
        "ok": True,
        "applied": list(updates.keys()),
        "vars": [
            {"key": k, "value": v, "is_secret": secret}
            for k, v, secret in rows
        ],
        "restart_required": _restart_required(list(updates.keys())),
    }


# ── /api/provider ─────────────────────────────────────────────────────────


@router.get("/api/provider")
async def get_provider() -> dict[str, Any]:
    cfg = config.get_provider_config()
    return {
        "provider":   cfg.provider,
        "model":      cfg.model,
        "providers":  list(_VALID_PROVIDERS),
        "model_var":  _PROVIDER_MODEL_VAR.get(cfg.provider),
    }


@router.patch("/api/provider")
async def patch_provider(body: ProviderUpdate) -> dict[str, Any]:
    if not body.provider and not body.model:
        raise HTTPException(status_code=400, detail="Provide provider and/or model")

    updates: dict[str, str] = {}
    target_provider = body.provider or config.PROVIDER

    if body.provider:
        if body.provider not in _VALID_PROVIDERS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown provider {body.provider!r}. "
                       f"Use one of {list(_VALID_PROVIDERS)}.",
            )
        updates["CHIKA_PROVIDER"] = body.provider

    if body.model:
        var = _PROVIDER_MODEL_VAR.get(target_provider)
        if not var:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot set model for provider {target_provider!r}",
            )
        updates[var] = body.model

    try:
        env_file.write_env(updates)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "ok":               True,
        "provider":         target_provider,
        "model":            body.model or config.get_provider_config().model,
        "applied":          list(updates.keys()),
        "restart_required": True,
    }


# ── Helpers ─────────────────────────────────────────────────────────────


def _restart_required(keys: list[str]) -> bool:
    """Some env keys are read once at process boot — flag those for the UI."""
    runtime_keys = {
        "CHIKA_PROVIDER",
        "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY",
        "OPENAI_MODEL", "OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY", "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_API_VERSION",
        "OLLAMA_BASE_URL", "OLLAMA_MODEL",
        "CHIKA_HOST", "CHIKA_PORT", "CHIKA_API_KEY",
        "CHIKA_THINKING", "CHIKA_THINKING_BUDGET",
        "CHIKA_MAX_HISTORY_TOKENS", "CHIKA_MAX_TOOL_TURNS",
        "CHIKA_MAX_MEMORY_TOKENS",
    }
    return any(k in runtime_keys for k in keys)
