from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_auth
from api.session_manager import session_manager

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/profile/{profile_name}/chats")
async def list_profile_chats(profile_name: str):
    return session_manager._chat_store.list_chats(profile_name)


@router.delete("/api/profile/{profile_name}/chats/{chat_id}")
async def delete_profile_chat(profile_name: str, chat_id: str):
    deleted = session_manager._chat_store.delete(profile_name, chat_id)
    session_manager.delete(chat_id)
    return {"deleted": deleted, "id": chat_id}
