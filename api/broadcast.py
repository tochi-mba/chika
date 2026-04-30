"""Shared frontend-socket registry and broadcast helper."""
from __future__ import annotations

import asyncio

from fastapi import WebSocket

_frontend_sockets: set[WebSocket] = set()
_frontend_sockets_lock = asyncio.Lock()


async def push_to_all_frontend_sessions(event: dict) -> None:
    """Broadcast an event dict to every connected frontend WebSocket."""
    async with _frontend_sockets_lock:
        sockets = list(_frontend_sockets)
    dead: set[WebSocket] = set()
    for ws in sockets:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    if dead:
        async with _frontend_sockets_lock:
            _frontend_sockets.difference_update(dead)
