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
    engine = session_manager.get_or_create("__meta__")
    return {"skills": engine._skills.list_skills()}


@router.get("/api/workflows")
async def get_workflows():
    engine = session_manager.get_or_create("__meta__")
    return {"workflows": list(engine._workflow_engine._sub_workflows.keys())}
