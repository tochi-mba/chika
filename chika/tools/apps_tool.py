from __future__ import annotations

import asyncio
import os
import platform
import subprocess

from chika.core.tool_registry import ToolDefinition


async def app_open(target: str) -> dict:
    """
    Open an application, file, folder, or URL on the host machine.
    Uses the OS-native launcher so it respects default app associations.
    """
    system = platform.system()
    try:
        if system == "Windows":
            # os.startfile is the cleanest Windows launcher — no cmd.exe, no exit-code ambiguity
            await asyncio.get_event_loop().run_in_executor(None, os.startfile, target)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return {"opened": target, "platform": system, "success": True}
    except Exception as exc:
        return {"opened": target, "platform": system, "success": False, "error": str(exc)}


APP_OPEN_TOOL = ToolDefinition(
    name="app_open",
    description=(
        "Open an application, file, folder, or URL on the host machine using the OS default launcher. "
        "Examples: 'notepad', 'chrome', 'spotify', 'C:/Users/me/doc.pdf', 'https://google.com', 'C:/Projects/'. "
        "Works on Windows (start), macOS (open), and Linux (xdg-open). "
        "Use this whenever you have a URL or file path relevant to the user's request — do NOT just print a link."
    ),
    requires_approval=False,
    parameters={
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "App name, URL, file path, or folder to open. Examples: 'https://youtube.com/@PewDiePie', 'notepad', 'spotify', 'C:/Projects/'",
            },
        },
        "required": ["target"],
    },
    handler=app_open,
)
