"""
live_server tool — spin up a local HTTP server for HTML/JS apps.

Avoids the file:// origin issues (blocked ES modules, fetch, etc.)
that make browser-opened HTML apps show blank screens.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import threading
import webbrowser
from typing import Any

from chika.core.tool_registry import ToolDefinition
from chika.tools.shell_tool import ManagedProcess, ProcessRegistry


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _already_serving(directory: str) -> dict | None:
    """Return info if we already have a live server for this directory."""
    norm = os.path.normcase(os.path.abspath(directory))
    for info in ProcessRegistry.all():
        if not info["running"]:
            continue
        cmd = info.get("command", "")
        if "http.server" in cmd and norm in os.path.normcase(cmd):
            return info
    return None


async def live_server(directory: str = "", port: int = 0, **kwargs) -> dict:
    """Start a local HTTP server in *directory* and open it in the browser."""
    if not directory:
        directory = kwargs.get("path", "")
    if not directory:
        return {"error": "Missing required argument: directory"}
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        return {"error": f"Directory does not exist: {directory}"}

    existing = _already_serving(directory)
    if existing:
        url = f"http://localhost:{existing.get('port', '?')}"
        webbrowser.open(url)
        return {
            "url": url,
            "pid": existing["pid"],
            "port": existing.get("port"),
            "already_running": True,
        }

    if port == 0:
        port = _find_free_port()

    python = sys.executable
    # Use list-form (shell=False) to avoid shell injection via directory names
    # that contain quotes, spaces, or other shell metacharacters.
    cmd_args = [python, "-m", "http.server", str(port), "--directory", directory]
    # Human-readable string kept for logging and _already_serving() matching
    cmd_display = f"{python} -m http.server {port} --directory {directory}"

    try:
        popen = subprocess.Popen(
            cmd_args,
            shell=False,
            cwd=directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        return {"error": f"Failed to start server: {exc}"}

    class _FakeAsyncProc:
        def __init__(self, p):
            self._p = p
            self.returncode = None

        @property
        def pid(self):
            return self._p.pid

        def kill(self):
            try:
                self._p.kill()
            except Exception:
                pass

        async def wait(self):
            return await asyncio.to_thread(self._p.wait)

    fake = _FakeAsyncProc(popen)
    managed = ManagedProcess(pid=popen.pid, command=cmd_display, process=fake)
    ProcessRegistry.register(managed)

    def _reader(stream, buf):
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                buf.append(line.rstrip("\r\n"))
        except Exception:
            pass

    threading.Thread(target=_reader, args=(popen.stdout, managed.stdout_buf), daemon=True).start()
    threading.Thread(target=_reader, args=(popen.stderr, managed.stderr_buf), daemon=True).start()

    async def _watch():
        rc = await asyncio.to_thread(popen.wait)
        managed.running = False
        managed.exit_code = rc
        fake.returncode = rc

    asyncio.create_task(_watch())

    # Brief pause so the server binds before we open the browser
    await asyncio.sleep(0.5)

    url = f"http://localhost:{port}"
    webbrowser.open(url)

    return {"url": url, "pid": popen.pid, "port": port, "directory": directory}


LIVE_SERVER_TOOL = ToolDefinition(
    name="live_server",
    description=(
        "Start a local HTTP server for an HTML/JS project directory and open it in the browser. "
        "Use this instead of app_open for HTML apps — it avoids file:// origin issues that break "
        "ES modules, fetch, and other web APIs. Returns {url, pid, port}. "
        "The server runs in the background; use shell_kill(pid) to stop it."
    ),
    requires_approval=False,
    parameters={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Absolute path to the directory containing index.html",
            },
            "port": {
                "type": "integer",
                "description": "Port to serve on (default 0 = auto-pick a free port)",
            },
        },
        "required": ["directory"],
    },
    handler=live_server,
)
