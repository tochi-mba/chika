from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_auth
from api.session_manager import session_manager

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/tools")
async def get_tools():
    engine = session_manager.get_or_create("__meta__")
    tools = []
    for name in engine._tools.names():
        t = engine._tools.get(name)
        if t:
            tools.append({"name": t.name, "description": t.description, "parameters": t.parameters})
    return {"tools": tools, "count": len(tools)}


@router.get("/api/skills")
async def get_skills():
    """Return every skill the engine knows about, with disabled state.

    Shape:
        {
          "skills": [
            {name, description, tools: [...], disabled: bool},
            ...
          ],
          "disabled": [<name>, ...]   # mirrors settings.skills_disabled
        }

    The Vue Skills tab uses this to render the per-skill toggle list.
    Always includes EVERY known skill (including the disabled ones)
    so the UI can show them as "off" — not just the live-registered
    ones in the engine.
    """
    import api.settings_store as _settings
    engine = session_manager.get_or_create("__meta__")
    disabled = list(_settings.get("skills_disabled", []) or [])
    disabled_set = set(disabled)

    # Live-registered skills (full info: description + tools)
    live = engine._skills.list_skills()
    live_by_name = {s["name"]: s for s in live}

    # Plus every name in the builders dict (so a disabled skill still
    # appears in the list as "off"). builders are stashed on every
    # session-built engine — the meta engine has them too.
    all_names: set[str] = set(live_by_name.keys())
    builders = getattr(engine, "_skill_builders", None) or {}
    all_names.update(builders.keys())

    skills_out = []
    for name in sorted(all_names):
        if name in live_by_name:
            entry = dict(live_by_name[name])
        else:
            # Disabled skill — surface with empty tool list so the UI
            # still has the row to render.
            entry = {"name": name, "description": "", "tools": []}
        entry["disabled"] = name in disabled_set
        skills_out.append(entry)
    return {"skills": skills_out, "disabled": disabled}


@router.get("/api/workflows")
async def get_workflows():
    engine = session_manager.get_or_create("__meta__")
    return {"workflows": list(engine._workflow_engine._sub_workflows.keys())}
