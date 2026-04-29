from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict          # JSON Schema object
    handler: Callable
    requires_approval: bool = False   # If True, engine pauses and waits for user approval before running
    approval_message: str = ""        # Human-readable reason shown in the approval dialog
    # approval_type controls what the approval dialog shows:
    #   "confirm"         — standard Yes/No
    #   "set_password"    — password input (optional) for setting/clearing a password
    #   "verify_password" — password input (required) for authentication
    approval_type: str = "confirm"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    async def dispatch(self, name: str, args: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name!r}"}
        import asyncio as _asyncio
        try:
            result = tool.handler(**args)
            if hasattr(result, "__await__"):
                result = await result
            return result
        except _asyncio.CancelledError:
            # Always propagate cancellation — never swallow it into an error
            # dict, or the caller can't tell the task was interrupted. This
            # was the source of mysterious `{"error": ""}` results.
            raise
        except Exception as exc:
            # Always include exception type + message (never empty) so logs
            # and tool_result payloads are diagnosable.
            msg = str(exc) or repr(exc)
            return {"error": f"{type(exc).__name__}: {msg}"}

    def list_for_prompt(self) -> list[dict]:
        """Return a compact list of {name, description} for the system prompt."""
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    def openai_schemas(self) -> list[dict]:
        """Return OpenAI-format tool schemas (for providers that use tool-call API)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]
