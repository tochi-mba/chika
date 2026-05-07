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

# Env keys whose change triggers a live ``reload_client()`` on every
# engine — i.e. the next chat turn picks up the new value with no
# process restart. Anything outside this set still flags
# ``restart_required: True``.
_HOT_RELOADABLE_ENV_KEYS = frozenset({
    "CHIKA_PROVIDER",
    "ANTHROPIC_MODEL", "ANTHROPIC_API_KEY",
    "OPENAI_MODEL", "OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY",
    "AZURE_OPENAI_DEPLOYMENT", "AZURE_API_VERSION",
    "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "CHIKA_THINKING", "CHIKA_THINKING_BUDGET",
    "CHIKA_VALIDATE_RESPONSE", "CHIKA_GROUNDING_MIN_LENGTH",
    "CHIKA_AUTONOMY",
    # Spotify integration: hot-reload picks up a freshly-pasted
    # CLIENT_ID from the inline Settings input without a restart.
    "CHIKA_SPOTIFY_CLIENT_ID", "CHIKA_SPOTIFY_REDIRECT_URI",
})


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

    # Hot-reload every engine's LLM client when any provider/model/api-key
    # variable changed. Other runtime knobs (host/port) still require a
    # restart — the response's ``restart_required`` flag tells the UI
    # which case applies.
    hot_reload = None
    if any(k in _HOT_RELOADABLE_ENV_KEYS for k in updates):
        hot_reload = _hot_reload_clients()

    rows = env_file.read_env_for_display(mask_secrets=True)
    return {
        "ok": True,
        "applied": list(updates.keys()),
        "vars": [
            {"key": k, "value": v, "is_secret": secret}
            for k, v, secret in rows
        ],
        "restart_required": _restart_required(list(updates.keys())),
        "hot_reload": hot_reload,
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

    updates: dict[str, str | None] = {}
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

    # Hot-swap every active engine's LLM client so the next turn on
    # any open session uses the new provider/model. Surfaces any
    # per-engine failure (e.g. missing API key for the new provider)
    # in the response so the UI can show a sharp error instead of a
    # silent "you must restart" footnote.
    summary = _hot_reload_clients()

    return {
        "ok":               True,
        "provider":         target_provider,
        "model":            body.model or config.get_provider_config().model,
        "applied":          list(updates.keys()),
        # Restart no longer required for provider/model swaps — kept
        # at False so the UI shows "✓ switched live" instead of
        # "restart needed".
        "restart_required": False,
        "hot_reload":       summary,
    }


# ── Helpers ─────────────────────────────────────────────────────────────


def _hot_reload_clients() -> dict[str, Any]:
    """Trigger every per-skill / per-engine reload hook.

    Order matters: ``config.reload_from_env`` (called inside
    ``session_manager.reload_clients``) refreshes the LLM globals
    first, then we fan out to per-skill modules whose own globals
    also need re-reading from the same .env (e.g. spotify CLIENT_ID).

    Returns a summary safe to embed in the HTTP response. Soft-fails
    on any error so a single failing hook doesn't lock the user out
    of the rest of the .env editor.
    """
    try:
        from api.session_manager import session_manager
        summary = session_manager.reload_clients()
    except Exception as exc:
        return {"error": str(exc), "changed": False, "sessions": 0}

    # Fan out to every skill via the subscription bus. Each skill's
    # ``on_env_changed`` hook decides which env vars matter to it
    # (the spotify integration, for example, listens for
    # ``CHIKA_SPOTIFY_CLIENT_ID``). The router doesn't have to know
    # which skill owns which var.
    try:
        import os

        from chika.skills import fire_env_changed
        for name, value in os.environ.items():
            fire_env_changed(name, value, None)
    except Exception:
        pass

    return summary


def _restart_required(keys: list[str]) -> bool:
    """True iff any changed env key still requires a process restart.

    Kept for /api/env path where users edit arbitrary env vars (host,
    port, max_history_tokens etc.). Provider/model are no longer in
    this list — they hot-reload via reload_client().
    """
    runtime_keys = {
        # Provider/model intentionally absent — handled by reload_client
        "AZURE_API_VERSION",  # part of azure auth, but reload_client picks it up
        "CHIKA_HOST", "CHIKA_PORT", "CHIKA_API_KEY",
        "CHIKA_MAX_HISTORY_TOKENS", "CHIKA_MAX_TOOL_TURNS",
        "CHIKA_MAX_MEMORY_TOKENS",
    }
    # AZURE_API_VERSION is reload-able too — pull it out of restart-required.
    runtime_keys.discard("AZURE_API_VERSION")
    return any(k in runtime_keys for k in keys)
