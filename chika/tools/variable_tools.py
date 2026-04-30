"""
Variable tools — expose the VariableStore to the AI as explicit tools.
Injected at startup via closure.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from chika.core.tool_registry import ToolDefinition
from chika.core.variable_store import VarType

if TYPE_CHECKING:
    from chika.core.variable_store import VariableStore


def make_variable_tools(store: VariableStore) -> list[ToolDefinition]:
    async def set_variable(name: str, value: object, var_type: str = "text", description: str = "") -> dict:
        try:
            t = VarType(var_type)
        except ValueError:
            t = VarType.TEXT
        v = store.set(name.lstrip("$"), value, t, description)
        return {"name": f"${v.name}", "type": v.type.value, "size_bytes": v.size_bytes}

    async def get_variable(name: str) -> dict:
        var = store.get(name.lstrip("$"))
        if var is None:
            return {"error": f"Variable '{name}' not found"}
        return {"name": f"${var.name}", "type": var.type.value,
                "size_bytes": var.size_bytes, "value": var.value}

    async def list_variables() -> dict:
        return {"variables": store.list_summary()}

    async def delete_variable(name: str) -> dict:
        store.delete(name.lstrip("$"))
        return {"deleted": name}

    return [
        ToolDefinition(
            name="set_variable",
            description="Store a value as a named $variable for use in subsequent workflow steps.",
            parameters={
                "type": "object",
                "properties": {
                    "name":        {"type": "string", "description": "Variable name (with or without $)"},
                    "value":       {"description": "Value to store — string, number, object, or array"},
                    "var_type":    {"type": "string", "enum": ["text", "json", "bytes", "file_path"]},
                    "description": {"type": "string"},
                },
                "required": ["name", "value"],
            },
            handler=set_variable,
        ),
        ToolDefinition(
            name="get_variable",
            description="Retrieve a $variable's current value.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=get_variable,
        ),
        ToolDefinition(
            name="list_variables",
            description="List all variables in the current session.",
            parameters={"type": "object", "properties": {}},
            handler=list_variables,
        ),
        ToolDefinition(
            name="delete_variable",
            description="Delete a variable from the session.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=delete_variable,
        ),
    ]
