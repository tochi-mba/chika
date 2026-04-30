from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from chika.core.tool_registry import ToolDefinition

# ── Process registry ──────────────────────────────────────────────────────────

@dataclass
class ManagedProcess:
    pid: int
    command: str
    process: Any
    stdout_buf: list[str] = field(default_factory=list)
    stderr_buf: list[str] = field(default_factory=list)
    running: bool = True
    exit_code: int | None = None


class ProcessRegistry:
    """Global registry of background shell processes, keyed by pid."""
    _procs: dict[int, ManagedProcess] = {}

    @classmethod
    def register(cls, proc: ManagedProcess) -> None:
        cls._procs[proc.pid] = proc

    @classmethod
    def get(cls, pid: int) -> ManagedProcess | None:
        return cls._procs.get(pid)

    @classmethod
    def all(cls) -> list[dict]:
        result = []
        for p in cls._procs.values():
            result.append({
                "pid": p.pid,
                "command": p.command,
                "running": p.running,
                "exit_code": p.exit_code,
                "stdout_lines": len(p.stdout_buf),
                "stderr_lines": len(p.stderr_buf),
            })
        return result

    @classmethod
    def remove(cls, pid: int) -> None:
        cls._procs.pop(pid, None)


# ── Background reader ─────────────────────────────────────────────────────────

async def _read_stream_into_buf(stream: asyncio.StreamReader | None, buf: list[str]) -> None:
    """
    Continuously read from a stream and append COMPLETE LINES to buf.

    asyncio.StreamReader.readline() on Windows sometimes returns partial reads
    one byte at a time when the subprocess flushes per-character. That turned
    `echo one` into 6 separate buffer entries (o,n,e, ,\r,\n). We now read
    chunks into a carry buffer and split on real newline boundaries.
    """
    if stream is None:
        return
    carry = ""
    try:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            carry += chunk.decode(errors="replace")
            # Split on any newline, keep the last incomplete fragment for next iter
            parts = carry.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            carry = parts.pop()  # last piece may be incomplete
            for line in parts:
                buf.append(line)
    except Exception as exc:
        # Surface stream reader crashes instead of silently leaving the buffer
        # frozen. Symptom of the old bug: background process appears healthy
        # (running: True) but stdout suddenly stops — hard to diagnose. Now
        # the error lands in the buffer itself.
        if carry:
            buf.append(carry)
            carry = ""
        buf.append(f"[stream reader error: {type(exc).__name__}: {exc}]")
    # Flush any residual partial line
    if carry:
        buf.append(carry)


# ── shell_exec ────────────────────────────────────────────────────────────────

@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    pid: int | None = None

    def to_dict(self) -> dict:
        MAX_CHARS = 4000
        stdout = self.stdout
        stderr = self.stderr
        extra: dict = {}

        if len(stdout) > MAX_CHARS:
            lines = stdout.splitlines()
            head = "\n".join(lines[:60])
            tail = "\n".join(lines[-20:])
            stdout = (
                f"{head}\n\n"
                f"... [{len(lines)} lines total — truncated. "
                f"Pipe to a file and use file_read with start_line/end_line to read it in chunks] ...\n\n"
                f"{tail}"
            )
            extra["stdout_truncated"] = True
            extra["total_stdout_lines"] = len(lines)

        if len(stderr) > MAX_CHARS:
            stderr = stderr[:MAX_CHARS] + f"\n... [stderr truncated at {MAX_CHARS} chars]"

        result = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "pid": self.pid,
            "stdout_lines": [l for l in self.stdout.splitlines() if l.strip()][:100],
            **extra,
        }

        # Surface non-zero exit as a warning so the LLM can detect command failures.
        # Not a hard "error" (that would abort sequentials for normal grep no-match etc.)
        # but a visible "warning" field the LLM and logs can see.
        if self.exit_code != 0 and not self.timed_out:
            result["warning"] = f"Command exited with non-zero code {self.exit_code}. Check stderr for details."

        return result


async def _shell_exec_threaded(
    command: str,
    timeout_seconds: float,
    wait_for_completion: bool,
    working_directory: str | None,
) -> dict:
    """
    Fallback shell_exec that doesn't need asyncio subprocess support.

    On Windows Selector event loops (uvicorn's default on some setups),
    `asyncio.create_subprocess_shell` raises NotImplementedError. This
    fallback uses plain blocking `subprocess.run` / `subprocess.Popen`
    dispatched via `asyncio.to_thread`, which works on any loop type.
    """
    import subprocess as _subproc
    import threading as _threading

    if wait_for_completion:
        def _run_sync() -> dict:
            try:
                r = _subproc.run(
                    command,
                    shell=True,
                    cwd=working_directory,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=timeout_seconds,
                )
                return ShellResult(
                    stdout=r.stdout or "",
                    stderr=r.stderr or "",
                    exit_code=r.returncode,
                    timed_out=False,
                    pid=-1,  # subprocess.run doesn't expose pid after completion
                ).to_dict()
            except _subproc.TimeoutExpired:
                return ShellResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout_seconds}s",
                    exit_code=-1,
                    timed_out=True,
                    pid=-1,
                ).to_dict()
            except Exception as exc:
                return {
                    "stdout": "", "stderr": "",
                    "exit_code": -1, "timed_out": False, "pid": -1,
                    "stdout_lines": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }

        return await asyncio.to_thread(_run_sync)

    # Background (wait_for_completion=False): spawn via Popen + thread readers
    try:
        popen = _subproc.Popen(
            command,
            shell=True,
            cwd=working_directory,
            stdout=_subproc.PIPE,
            stderr=_subproc.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line-buffered
        )
    except Exception as exc:
        return {
            "stdout": "", "stderr": "",
            "exit_code": -1, "timed_out": False, "pid": -1,
            "stdout_lines": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    # Wrap in a ManagedProcess with a None asyncio process — background readers
    # drain stdout/stderr via blocking threads.
    class _FakeAsyncProc:
        """Minimal shim so ManagedProcess.process.wait()/kill() work."""
        def __init__(self, popen): self._p = popen; self.returncode = None
        @property
        def pid(self): return self._p.pid
        def kill(self):
            try: self._p.kill()
            except Exception: pass
        async def wait(self):
            return await asyncio.to_thread(self._p.wait)

    fake_proc = _FakeAsyncProc(popen)
    managed = ManagedProcess(pid=popen.pid, command=command, process=fake_proc)
    ProcessRegistry.register(managed)

    def _reader(stream, buf: list[str]) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                buf.append(line.rstrip("\r\n"))
        except Exception as exc:
            buf.append(f"[stream reader error: {type(exc).__name__}: {exc}]")

    _threading.Thread(target=_reader, args=(popen.stdout, managed.stdout_buf), daemon=True).start()
    _threading.Thread(target=_reader, args=(popen.stderr, managed.stderr_buf), daemon=True).start()

    async def _watch_exit():
        rc = await asyncio.to_thread(popen.wait)
        managed.running = False
        managed.exit_code = rc
        fake_proc.returncode = rc
    asyncio.create_task(_watch_exit())

    return {
        "stdout": "", "stderr": "", "exit_code": -1,
        "timed_out": False, "pid": popen.pid, "stdout_lines": [],
        "status": "running",
        "message": f"Process started with pid={popen.pid}. Use shell_get_output({popen.pid}) to read output.",
    }


async def shell_exec(
    command: str,
    timeout_seconds: float = 90.0,
    wait_for_completion: bool = True,
    working_directory: str | None = None,
    **_extra_kwargs,  # absorb common mistakes like shell=True, cwd=, env=
) -> dict:
    # Accept common aliases silently rather than raising TypeError:
    # - cwd → working_directory (Python subprocess name)
    # - shell=True/False → ignored (we're always shelling out)
    if working_directory is None and "cwd" in _extra_kwargs:
        working_directory = _extra_kwargs.get("cwd")
    # Validate working_directory up-front so a bad path becomes a nice
    # structured error instead of propagating NotADirectoryError/FileNotFound
    # from create_subprocess_shell. (Observed in chika.log as mystery empty
    # error results when the LLM sent a malformed path.)
    if working_directory:
        import os as _os
        if not _os.path.isdir(working_directory):
            return {
                "stdout": "", "stderr": "",
                "exit_code": -1, "timed_out": False, "pid": -1,
                "stdout_lines": [],
                "error": f"working_directory does not exist or is not a directory: {working_directory!r}",
            }
    if not command or not command.strip():
        return {
            "stdout": "", "stderr": "",
            "exit_code": -1, "timed_out": False, "pid": -1,
            "stdout_lines": [],
            "error": "command is empty — pass a non-empty shell command",
        }

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_directory,
        )
    except NotImplementedError:
        # Windows Selector event loop (uvicorn's default on some setups)
        # cannot spawn subprocesses at all. Rather than fail the whole
        # command, fall through to a synchronous subprocess.run dispatched
        # via asyncio.to_thread — works on any event loop.
        return await _shell_exec_threaded(
            command=command,
            timeout_seconds=timeout_seconds,
            wait_for_completion=wait_for_completion,
            working_directory=working_directory,
        )
    except (NotADirectoryError, FileNotFoundError, OSError) as exc:
        # Defensive catch — even with the isdir check above, races or
        # permission issues could still raise. Always return a dict.
        return {
            "stdout": "", "stderr": "",
            "exit_code": -1, "timed_out": False, "pid": -1,
            "stdout_lines": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    # Register ALL processes so the shells monitor tab can show them
    managed = ManagedProcess(pid=proc.pid, command=command, process=proc)
    ProcessRegistry.register(managed)

    if not wait_for_completion:
        # Background: stream output into buffers continuously
        asyncio.create_task(_read_stream_into_buf(proc.stdout, managed.stdout_buf))
        asyncio.create_task(_read_stream_into_buf(proc.stderr, managed.stderr_buf))

        async def _watch_exit():
            await proc.wait()
            managed.running = False
            managed.exit_code = proc.returncode

        asyncio.create_task(_watch_exit())
        return {
            "stdout": "", "stderr": "", "exit_code": -1,
            "timed_out": False, "pid": proc.pid, "stdout_lines": [],
            "status": "running",
            "message": f"Process started with pid={proc.pid}. Use shell_get_output({proc.pid}) to read output.",
        }

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        stdout_text = stdout_b.decode(errors="replace")
        stderr_text = stderr_b.decode(errors="replace")
        # Populate buffers so the shells monitor shows the output
        managed.stdout_buf.extend(stdout_text.splitlines())
        managed.stderr_buf.extend(stderr_text.splitlines())
        managed.running = False
        managed.exit_code = proc.returncode or 0
        return ShellResult(
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=proc.returncode or 0,
            timed_out=False,
            pid=proc.pid,
        ).to_dict()
    except TimeoutError:
        proc.kill()
        managed.running = False
        managed.exit_code = -1
        return ShellResult(
            stdout="",
            stderr=f"Command timed out after {timeout_seconds}s",
            exit_code=-1,
            timed_out=True,
            pid=proc.pid,
        ).to_dict()


# ── shell_get_output ──────────────────────────────────────────────────────────

async def shell_get_output(pid: int, clear: bool = False) -> dict:
    """Read buffered output from a background process."""
    managed = ProcessRegistry.get(pid)
    if managed is None:
        return {"error": f"No process with pid={pid}. Use shell_list_processes() to see running processes."}

    stdout_lines = list(managed.stdout_buf)
    stderr_lines = list(managed.stderr_buf)

    if clear:
        managed.stdout_buf.clear()
        managed.stderr_buf.clear()

    return {
        "pid": pid,
        "command": managed.command,
        "running": managed.running,
        "exit_code": managed.exit_code,
        "stdout": "\n".join(stdout_lines),
        "stdout_lines": stdout_lines,
        "stderr": "\n".join(stderr_lines),
        "stderr_lines": stderr_lines,
        "total_stdout_lines": len(stdout_lines),
    }


# ── shell_kill ────────────────────────────────────────────────────────────────

async def shell_kill(pid: int) -> dict:
    """Kill a background process by pid."""
    managed = ProcessRegistry.get(pid)
    if managed is None:
        return {"error": f"No process with pid={pid}"}
    if not managed.running:
        return {"pid": pid, "already_exited": True, "exit_code": managed.exit_code}
    try:
        managed.process.kill()
        managed.running = False
        return {"pid": pid, "killed": True}
    except Exception as e:
        return {"error": str(e)}


# ── shell_list_processes ──────────────────────────────────────────────────────

async def shell_list_processes() -> dict:
    """List all tracked background processes and their status."""
    return {"processes": ProcessRegistry.all()}


# ── shell_wait ────────────────────────────────────────────────────────────────

async def shell_wait(pid: int, timeout_seconds: float = 60.0) -> dict:
    """Wait for a background process to finish, then return its full output."""
    managed = ProcessRegistry.get(pid)
    if managed is None:
        return {"error": f"No process with pid={pid}"}
    try:
        await asyncio.wait_for(managed.process.wait(), timeout=timeout_seconds)
        managed.running = False
        managed.exit_code = managed.process.returncode
        return await shell_get_output(pid)
    except TimeoutError:
        return {
            "pid": pid, "timed_out": True,
            "stdout_lines": list(managed.stdout_buf),
            "stderr_lines": list(managed.stderr_buf),
            "running": managed.running,
        }


# ── ToolDefinitions ───────────────────────────────────────────────────────────

SHELL_TOOL = ToolDefinition(
    name="shell_exec",
    description=(
        "Run a shell command. "
        "wait_for_completion=true (default): blocks and returns stdout/stderr/exit_code. "
        "wait_for_completion=false: fires in background, returns pid immediately — "
        "use shell_get_output(pid) to poll output, shell_wait(pid) to block until done."
    ),
    requires_approval=True,
    approval_message="Chika wants to run a shell command on your system.",
    parameters={
        "type": "object",
        "properties": {
            "command":             {"type": "string",  "description": "Shell command to execute"},
            "timeout_seconds":     {"type": "number",  "description": "Max seconds to wait (default 30, only for wait_for_completion=true)"},
            "wait_for_completion": {"type": "boolean", "description": "false = fire and forget, returns pid immediately"},
            "working_directory":   {"type": "string",  "description": "Working directory for the command"},
        },
        "required": ["command"],
    },
    handler=shell_exec,
)

SHELL_GET_OUTPUT_TOOL = ToolDefinition(
    name="shell_get_output",
    description="Read buffered stdout/stderr from a background process started with shell_exec(wait_for_completion=false). Pass clear=true to drain the buffer.",
    parameters={
        "type": "object",
        "properties": {
            "pid":   {"type": "integer", "description": "Process ID returned by shell_exec"},
            "clear": {"type": "boolean", "description": "Clear the buffer after reading (default false)"},
        },
        "required": ["pid"],
    },
    handler=shell_get_output,
)

SHELL_KILL_TOOL = ToolDefinition(
    name="shell_kill",
    description="Kill a background process by pid.",
    requires_approval=True,
    approval_message="Chika wants to terminate a running background process.",
    parameters={
        "type": "object",
        "properties": {
            "pid": {"type": "integer", "description": "Process ID to kill"},
        },
        "required": ["pid"],
    },
    handler=shell_kill,
)

SHELL_LIST_TOOL = ToolDefinition(
    name="shell_list_processes",
    description="List all tracked background shell processes and their running status.",
    parameters={
        "type": "object",
        "properties": {},
    },
    handler=shell_list_processes,
)

SHELL_WAIT_TOOL = ToolDefinition(
    name="shell_wait",
    description="Wait for a background process to finish (up to timeout_seconds), then return its full output.",
    parameters={
        "type": "object",
        "properties": {
            "pid":             {"type": "integer", "description": "Process ID to wait for"},
            "timeout_seconds": {"type": "number",  "description": "Max seconds to wait (default 60)"},
        },
        "required": ["pid"],
    },
    handler=shell_wait,
)

ALL_SHELL_TOOLS = [SHELL_TOOL, SHELL_GET_OUTPUT_TOOL, SHELL_KILL_TOOL, SHELL_LIST_TOOL, SHELL_WAIT_TOOL]
