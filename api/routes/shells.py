"""``/api/shells`` — list, kill, kill-all background shell processes.

Surfaces the same ``ProcessRegistry`` the CLI's ``/shells`` command and
the agent's ``shell_kill`` / ``shell_get_output`` tools all share. The
frontend ShellsPanel and the extension popup talk to these endpoints to
show running PIDs and let the user terminate any of them with a click.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_auth
from chika.tools.shell_tool import ProcessRegistry

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/api/shells")
async def list_shells():
    """Return every tracked process: ``[{pid, command, running, exit_code, ...}]``."""
    return {"processes": ProcessRegistry.all()}


@router.post("/api/shells/{pid}/kill")
async def kill_shell(pid: int):
    """Kill one process by PID. Returns 404 if no such process is tracked."""
    managed = ProcessRegistry.get(pid)
    if managed is None:
        raise HTTPException(404, f"no tracked process with pid={pid}")
    if not managed.running:
        return {
            "ok":             True,
            "pid":            pid,
            "already_exited": True,
            "exit_code":      managed.exit_code,
        }
    try:
        managed.process.kill()
        managed.running = False
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc
    return {"ok": True, "pid": pid, "killed": True}


@router.post("/api/shells/kill_all")
async def kill_all_shells():
    """Kill every running process. Returns lists of killed and failed PIDs."""
    killed: list[int] = []
    failed: list[dict] = []
    for entry in ProcessRegistry.all():
        if not entry.get("running"):
            continue
        pid = entry.get("pid")
        managed = ProcessRegistry.get(pid)
        if managed is None or not managed.running:
            continue
        try:
            managed.process.kill()
            managed.running = False
            killed.append(pid)
        except Exception as exc:
            failed.append({"pid": pid, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": True, "killed": killed, "failed": failed}
