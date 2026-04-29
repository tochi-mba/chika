import asyncio
from chika.core.tool_registry import ToolDefinition


async def wait(seconds: float) -> dict:
    """Pause execution for N seconds (clamped to [0, 300])."""
    seconds = max(0.0, min(float(seconds), 300.0))
    await asyncio.sleep(seconds)
    return {"waited_seconds": seconds}


WAIT_TOOL = ToolDefinition(
    name="wait",
    description="Pause for N seconds. Use inside loop steps to poll for external state changes.",
    parameters={
        "type": "object",
        "properties": {
            "seconds": {"type": "number", "description": "Seconds to wait"},
        },
        "required": ["seconds"],
    },
    handler=wait,
)
