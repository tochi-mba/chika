"""
Memory tools — thin wrappers around MemoryManager.
The MemoryManager instance is injected at startup via closure.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from chika.core.tool_registry import ToolDefinition

if TYPE_CHECKING:
    from chika.core.memory_manager import MemoryManager


def make_memory_tools(memory: "MemoryManager") -> list[ToolDefinition]:
    async def memory_persist(key: str, value: str, ttl_days: int | None = None) -> dict:
        memory.persist(key, value, ttl_days)
        return {"ok": True, "key": key}

    async def memory_forget(key: str) -> dict:
        memory.forget(key)
        return {"ok": True, "key": key}

    async def memory_read(key: str) -> dict:
        value = memory.read(key)
        if value is None:
            return {"error": f"Key not found: {key!r}"}
        return {"key": key, "value": value}

    async def memory_list(_: str = "") -> dict:
        return {"keys": memory.list_keys(), "entries": memory.all_entries()}

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
