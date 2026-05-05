"""``/api/profiles`` — list, create, authenticate, switch, password.

The frontend and extension both gate the chat surface behind a profile
pick. They call:

  GET  /api/profiles                  → list (name + has_password)
  POST /api/profiles/create           → make a new profile
  POST /api/profiles/authenticate     → verify password (no session change)
  POST /api/profiles/select           → set the active profile for ``session_id``
  POST /api/profiles/{name}/password  → set/clear a password

Auth on each route is ``require_auth`` (the global Bearer token). The
profile password is a SECOND factor on top — it gates access to that
profile's memory + workspace + chat history within an already-authed
client.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import require_auth
from api.session_manager import session_manager

router = APIRouter(dependencies=[Depends(require_auth)])


# ── Schemas ──────────────────────────────────────────────────────────────


class _CreateProfile(BaseModel):
    name:     str            = Field(..., min_length=1, max_length=64)
    password: str | None     = Field(default=None, max_length=256)


class _AuthenticateProfile(BaseModel):
    name:     str            = Field(..., min_length=1, max_length=64)
    password: str            = Field(default="", max_length=256)


class _SelectProfile(BaseModel):
    session_id: str          = Field(..., min_length=1, max_length=128)
    name:       str          = Field(..., min_length=1, max_length=64)
    password:   str          = Field(default="", max_length=256)


class _SetPassword(BaseModel):
    old_password: str        = Field(default="", max_length=256)
    new_password: str        = Field(default="", max_length=256)


# ── Routes ──────────────────────────────────────────────────────────────


@router.get("/api/profiles")
async def list_profiles():
    """Return every profile + whether it requires a password.

    Shape: ``{profiles: [{name, has_password}], default_password_required: bool}``.
    """
    pm = session_manager._profile_manager
    names = pm.list_profiles()
    return {
        "profiles": [
            {"name": n, "has_password": pm.has_password(n)} for n in names
        ],
    }


@router.post("/api/profiles/create")
async def create_profile(body: _CreateProfile):
    """Create a profile (and optionally set a password). Idempotent: if the
    profile already exists, the password is updated (or cleared) instead.

    Returns ``{ok, name, has_password}``.
    """
    pm = session_manager._profile_manager
    try:
        profile = pm.get_or_create(body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if body.password is not None:
        pm.set_password(profile.name, body.password or "")
    return {
        "ok":           True,
        "name":         profile.name,
        "has_password": pm.has_password(profile.name),
    }


@router.post("/api/profiles/authenticate")
async def authenticate_profile(body: _AuthenticateProfile):
    """Verify a profile's password without changing session state.

    Frontend uses this for "tell me if this password is right" flows
    before committing to the WebSocket connect.
    """
    pm = session_manager._profile_manager
    if not pm.exists(body.name):
        raise HTTPException(404, f"profile {body.name!r} not found")
    if not pm.verify_password(body.name, body.password):
        raise HTTPException(401, "incorrect password")
    return {"ok": True, "name": body.name}


@router.post("/api/profiles/select")
async def select_profile(body: _SelectProfile):
    """Switch the active profile for a given chat session.

    Verifies the password (or accepts the empty string when none is set),
    then calls ``engine.switch_profile`` so subsequent messages run
    against that profile's memory + workspace.
    """
    pm = session_manager._profile_manager
    if not pm.exists(body.name):
        raise HTTPException(404, f"profile {body.name!r} not found")
    if not pm.verify_password(body.name, body.password):
        raise HTTPException(401, "incorrect password")

    engine = session_manager.get_or_create(body.session_id)
    profile = pm.get_or_create(body.name)
    engine.switch_profile(profile)
    return {
        "ok":            True,
        "name":          profile.name,
        "workspace":     profile.workspace,
        "pet_id":        profile.pet_id,
    }


@router.post("/api/profiles/{name}/password")
async def set_profile_password(name: str, body: _SetPassword):
    """Set, change, or clear a profile's password.

    - Setting where none exists is allowed when ``old_password`` is empty.
    - Changing requires the correct ``old_password``.
    - Clearing is signalled by ``new_password=""``.
    """
    pm = session_manager._profile_manager
    if not pm.exists(name):
        raise HTTPException(404, f"profile {name!r} not found")
    if pm.has_password(name) and not pm.verify_password(name, body.old_password):
        raise HTTPException(401, "old password is incorrect")
    pm.set_password(name, body.new_password or "")
    return {"ok": True, "name": name, "has_password": pm.has_password(name)}
