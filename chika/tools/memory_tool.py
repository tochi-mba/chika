"""
Memory tools — thin wrappers around the session's MemoryManager.

IMPORTANT: the tools look up `engine._memory` at call time, not at
registration time. If they captured the memory manager via closure at
registration, a later switch_profile() would replace engine._memory but
the tools would still write to the original — that's how memory_persist
calls for user 'alex' ended up in default/memory.md.
"""
from __future__ import annotations

from chika.core.tool_registry import ToolDefinition


def make_memory_tools(engine) -> list[ToolDefinition]:
    def _mem():
        """Resolve the CURRENT memory manager every call — follows profile switches."""
        return engine._memory

    async def memory_persist(key: str, value: str, ttl_days: int | None = None) -> dict:
        _mem().persist(key, value, ttl_days)
        return {
            "ok": True, "key": key,
            "profile": engine._active_profile.name if engine._active_profile else None,
        }

    async def memory_forget(key: str) -> dict:
        _mem().forget(key)
        return {"ok": True, "key": key}

    async def memory_read(key: str) -> dict:
        value = _mem().read(key)
        if value is None:
            return {"error": f"Key not found: {key!r}"}
        return {"key": key, "value": value}

    async def memory_list(_: str = "") -> dict:
        m = _mem()
        return {"keys": m.list_keys(), "entries": m.all_entries()}

    return [
        ToolDefinition(
            name="memory_persist",
            description="Save a value to persistent memory under a key. Optional TTL in days.",
            parameters={
                "type": "object",
                "properties": {
                    "key":      {"type": "string",  "description": "Memory key"},
                    "value":    {"type": "string",  "description": "Value to store"},
                    "ttl_days": {"type": "integer", "description": "Days until expiry (optional)"},
                },
                "required": ["key", "value"],
            },
            handler=memory_persist,
        ),
        ToolDefinition(
            name="memory_forget",
            description="Delete a memory entry by key.",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
            handler=memory_forget,
        ),
        ToolDefinition(
            name="memory_read",
            description="Read a value from persistent memory by key.",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
            handler=memory_read,
        ),
        ToolDefinition(
            name="memory_list",
            description="List all memory keys and entries.",
            parameters={"type": "object", "properties": {}},
            handler=memory_list,
        ),
    ]
