"""``/api/pets`` and ``/api/profile/{name}/pet`` — pet catalogue + per-profile selection.

The catalogue (``GET /api/pets``) is shared with the frontend so both the
Settings modal and the in-page pet widget render the same metadata. Each
profile owns its choice; the CLI and frontend read/write the same
``profile.json`` value.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_auth
from api.broadcast import push_to_all_frontend_sessions
from api.session_manager import session_manager
from chika._cli import pets as pet_lib

router = APIRouter(dependencies=[Depends(require_auth)])


class PetUpdate(BaseModel):
    pet_id: str | None  # None or "" clears the override
    # On a swap, the user can choose to carry the OLD pet's memory file
    # over to the new pet, or to start fresh. ``carry_memory`` defaults
    # to None (don't touch existing memory). Set ``carry`` to copy the
    # previous pet's memory.md to the new one. Set ``clear`` to wipe the
    # NEW pet's existing memory before activating it. ``carry`` wins if
    # both are passed (carry implies "we want this content", which the
    # explicit clear contradicts).
    memory_action: str | None = None  # "carry" | "clear" | None


# ── Catalogue ─────────────────────────────────────────────────────────────


@router.get("/api/pets")
async def list_pets() -> dict:
    return {"pets": pet_lib.all_pets(), "default": pet_lib.DEFAULT_PET_ID}


# ── Per-profile selection ─────────────────────────────────────────────────


@router.get("/api/profile/{name}/pet")
async def get_profile_pet(name: str) -> dict:
    pm = session_manager._profile_manager
    if not pm.exists(name):
        raise HTTPException(status_code=404, detail=f"Profile {name!r} not found")
    pet_id = pm.get_pet(name)
    pet = pet_lib.get(pet_id)
    return {
        "profile": name,
        "pet_id":  pet_id,
        "pet":     {
            "id":          pet.id,
            "name":        pet.name,
            "description": pet.description,
            "accent":      pet.accent,
            "emoji":       pet.emoji,
            "preview":     pet.frame_for("idle", 0),
        },
    }


@router.patch("/api/profile/{name}/pet")
async def set_profile_pet(name: str, body: PetUpdate) -> dict:
    pm = session_manager._profile_manager
    if not pm.exists(name):
        raise HTTPException(status_code=404, detail=f"Profile {name!r} not found")

    new_id = (body.pet_id or "").strip() or None
    if new_id and new_id not in pet_lib.PETS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown pet {new_id!r}. options: {sorted(pet_lib.PETS)}",
        )

    # Capture the OLD pet id BEFORE mutating profile state so we can
    # carry / clear memory based on the swap source.
    old_id = pm.get_pet(name)

    pm.set_pet(name, new_id)

    # Memory carry / clear handling. Only meaningful when an actual swap
    # is happening (old_id != new_id) and a workspace exists for the
    # profile.
    profile = pm.get(name)
    memory_changed: dict | None = None
    if profile and new_id and body.memory_action in ("carry", "clear"):
        # Sibling import — these helpers live next to us in the pet
        # skill's __init__.py. Used to be the cross-import the
        # api/routes/pets.py file had to allowlist; now invisible
        # because we ARE inside the skill folder.
        from chika.skills.pet_skill import (
            clear_pet_memory,
            copy_pet_memory,
        )
        ws = profile.workspace
        if body.memory_action == "carry" and old_id and old_id != new_id:
            copied = copy_pet_memory(ws, old_id, new_id)
            memory_changed = {"action": "carry", "from": old_id,
                              "to": new_id, "copied": copied}
        elif body.memory_action == "clear":
            cleared = clear_pet_memory(ws, new_id)
            memory_changed = {"action": "clear", "pet": new_id,
                              "cleared": cleared}

    # Update any live engine that has this profile loaded so the next CLI
    # / frontend tick reflects the change.
    for eng in session_manager._sessions.values():
        if eng._active_profile and eng._active_profile.name == name:
            eng._active_profile.pet_id = new_id

    # Broadcast so any open frontend tab re-renders its pet widget.
    await push_to_all_frontend_sessions({
        "type":    "pet_changed",
        "profile": name,
        "pet_id":  new_id,
    })

    payload = {"ok": True, "profile": name, "pet_id": new_id, "old_pet_id": old_id}
    if memory_changed is not None:
        payload["memory"] = memory_changed
    return payload
