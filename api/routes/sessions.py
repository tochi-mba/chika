from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_auth
from api.session_manager import session_manager

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/sessions")
async def list_sessions():
    return {"sessions": session_manager.list_sessions()}


@router.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    session_manager.delete(session_id)
    return {"deleted": session_id}


@router.post("/api/session/{session_id}/reset")
async def reset_session(session_id: str):
    engine = session_manager.get(session_id)
    if engine:
        engine.reset()
    return {"reset": session_id}


@router.get("/api/session/{session_id}/variables")
async def get_variables(session_id: str):
    engine = session_manager.get(session_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"variables": engine._vars.list_summary()}


@router.get("/api/session/{session_id}/memory")
async def get_memory(session_id: str):
    engine = session_manager.get(session_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"memory": engine._memory.all_entries()}


@router.get("/api/session/{session_id}/history")
async def get_history(session_id: str):
    engine = session_manager.get(session_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Session not found")
    history = [m for m in engine._history if m.get("role") != "system"]
    return {"history": history, "count": len(history)}
