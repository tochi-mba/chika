"""``python_run`` — run a Python script as a real desktop process.

Why this exists
---------------

``shell_exec("python foo.py", wait_for_completion=False)`` works for
console scripts but two things break for GUI apps (pygame, tkinter, etc.):

1. **No new console / window station**. On Windows, a process spawned from
   the engine inherits the parent's hidden subprocess flags. Some GUI
   libraries refuse to draw a window when stdout is a pipe.
2. **Silent ``ModuleNotFoundError``**. The script crashes within ~200ms
   and the agent moves on, never reading stderr. The user sees nothing.

This tool fixes both:

- Spawns Python with ``CREATE_NEW_CONSOLE`` on Windows (visible terminal +
  attached desktop session) so pygame/tk/PySide windows actually surface.
- Pre-flights ``import``\\s by parsing the script and trying each module;
  on the first ``ModuleNotFoundError`` it offers to ``pip install`` it
  automatically (gated on ``auto_install=True``).
- Polls for early exit so import errors land in the first tool result.

Use this for **windowed / GUI / interactive** programs. Plain CLI scripts
should stay on ``shell_exec`` so output streams back into the chat.
"""
from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

from chika.core.tool_registry import ToolDefinition
from chika.tools.shell_tool import (
    ManagedProcess,
    ProcessRegistry,
    _wait_for_early_exit,
)

# ── Pre-flight import checks ─────────────────────────────────────────────────


def _top_level_imports(script_path: Path) -> list[str]:
    """Best-effort static scan for top-level ``import`` / ``from`` modules.

    Only inspects the AST — never executes the script. Returns the *root*
    package names (``import pygame.locals`` → ``pygame``).
    """
    try:
        tree = ast.parse(script_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                out.add(node.module.split(".")[0])
    return sorted(out)


_STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {
    # Belt-and-braces for older Pythons
    "asyncio", "json", "os", "sys", "pathlib", "re", "math", "time",
    "subprocess", "threading", "typing", "dataclasses", "collections",
    "functools", "itertools", "random", "datetime", "enum", "io",
}


def _missing_modules(modules: list[str]) -> list[str]:
    """Return the subset of ``modules`` that aren't importable."""
    import importlib.util as _u
    missing: list[str] = []
    for mod in modules:
        if mod in _STDLIB:
            continue
        try:
            if _u.find_spec(mod) is None:
                missing.append(mod)
        except Exception:
            missing.append(mod)
    return missing


# Each entry maps an *import* name to the ordered list of pip distributions
# we should try. The first entry is the canonical name; later entries are
# fallbacks for when the canonical package has no wheel for the current
# Python version (very common for native-extension libraries on .x.0
# releases). Drop-in compatible alternatives only — pygame-ce ships its
# module as ``pygame``, so user code keeps working.
_PIP_ALTERNATIVES: dict[str, list[str]] = {
    "PIL":           ["Pillow"],
    "cv2":           ["opencv-python", "opencv-python-headless"],
    "yaml":          ["PyYAML"],
    "bs4":           ["beautifulsoup4"],
    "skimage":       ["scikit-image"],
    "sklearn":       ["scikit-learn"],
    "pygame":        ["pygame", "pygame-ce"],
    "psutil":        ["psutil"],
    "google.cloud":  ["google-cloud"],
}


def _pip_candidates(module: str) -> list[str]:
    """Ordered list of pip distribution names to try for an import."""
    return _PIP_ALTERNATIVES.get(module, [module])


def _summarise_pip_log(log: str) -> str:
    """Pull the meaningful error lines out of pip's verbose output.

    pip dumps hundreds of lines of "Downloading SDL2…" before the actual
    failure reason. Surfacing the noise to the LLM wastes tokens and hides
    the cause. We grab any ``ERROR:`` lines plus the tail.
    """
    lines = log.splitlines()
    err_lines = [ln for ln in lines if ln.startswith("ERROR:")
                 or "error:" in ln.lower()
                 or "FAILED" in ln]
    tail = lines[-15:]
    summary: list[str] = []
    for ln in err_lines + tail:
        if ln not in summary:
            summary.append(ln)
    return "\n".join(summary[-25:]).strip() or log[-1000:].strip()


def _classify_failure(log: str) -> str:
    """Best-effort error code from a pip log."""
    low = log.lower()
    if "no matching distribution found" in low:
        return "no_wheel_for_this_python"
    if ("microsoft visual c++" in low or "vcvarsall" in low
            or "build_ext" in low or "subprocess-exited-with-error" in low):
        return "compile_failed_no_toolchain"
    if "could not connect" in low or "temporary failure" in low \
            or "name resolution" in low:
        return "network_error"
    if "permission denied" in low or "access is denied" in low:
        return "permission_denied"
    return "unknown"


async def _try_install(distribution: str) -> tuple[int, str]:
    """Run ``pip install <distribution>`` once. Returns (returncode, log)."""
    # NOTE: no --quiet — we want pip's actual error text. We do disable the
    # version-check chatter and the cache-misses that flood the log.
    args = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check",
        "--no-input",
        distribution,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out_b, _ = await proc.communicate()
    return proc.returncode or 0, (out_b or b"").decode(errors="replace")


async def _install_module(import_name: str) -> dict:
    """Install one module by import name, walking the alternatives list.

    Returns a dict with the outcome: which distribution succeeded (if any),
    the failure reason, a clean log summary, and a `fix_command` the user
    can paste if every alternative fails.
    """
    candidates = _pip_candidates(import_name)
    attempts: list[dict] = []
    for dist in candidates:
        rc, log = await _try_install(dist)
        attempts.append({
            "distribution": dist,
            "returncode":   rc,
            "reason":       None if rc == 0 else _classify_failure(log),
            "log_tail":     _summarise_pip_log(log),
        })
        if rc == 0:
            return {
                "ok":            True,
                "import_name":   import_name,
                "installed_as":  dist,
                "attempts":      attempts,
            }
    # All candidates failed — synthesise a fix command the user can run.
    last = attempts[-1] if attempts else {"distribution": import_name}
    fix = f'{sys.executable} -m pip install {last["distribution"]}'
    return {
        "ok":            False,
        "import_name":   import_name,
        "attempts":      attempts,
        "fix_command":   fix,
        "reason":        attempts[-1]["reason"] if attempts else "unknown",
    }


# ── Spawn helpers ────────────────────────────────────────────────────────────


def _windows_creationflags() -> int:
    """``CREATE_NEW_CONSOLE`` so GUI windows attach to the user's desktop."""
    if sys.platform != "win32":
        return 0
    # 0x00000010 == CREATE_NEW_CONSOLE
    return 0x00000010


# ── Tool ─────────────────────────────────────────────────────────────────────


async def _python_run(
    script: str,
    args: list[str] | None = None,
    working_directory: str | None = None,
    auto_install: bool = True,
    new_console: bool = True,
    **_kw,
) -> Any:
    if not script or not isinstance(script, str):
        return {"error": "script must be a non-empty path string"}

    script_path = Path(script)
    if not script_path.is_absolute() and working_directory:
        script_path = Path(working_directory) / script
    if not script_path.exists():
        return {"error": f"script not found: {script_path}"}
    if script_path.suffix.lower() != ".py":
        return {"error": f"only .py files are supported (got {script_path.suffix!r})"}

    # 1. Pre-flight imports — install each missing module, walking
    # alternatives (pygame → pygame-ce, etc.) so a missing wheel for one
    # distribution doesn't doom the whole run.
    imports = _top_level_imports(script_path)
    missing = _missing_modules(imports)
    install_outcomes: list[dict] = []
    installed: list[str] = []
    if missing and auto_install:
        for mod in missing:
            outcome = await _install_module(mod)
            install_outcomes.append(outcome)
            if outcome["ok"]:
                installed.append(outcome["installed_as"])
        failed = [o for o in install_outcomes if not o["ok"]]
        if failed:
            # Surface a concise, actionable result. The agent should show
            # ``fix_command`` to the user verbatim — it works even when our
            # auto-install didn't.
            primary = failed[0]
            return {
                "error":          "pip_install_failed",
                "reason":         primary.get("reason"),
                "failed_module":  primary["import_name"],
                "tried":          [a["distribution"] for a in primary["attempts"]],
                "log_tail":       primary["attempts"][-1]["log_tail"] if primary["attempts"] else "",
                "fix_command":    primary["fix_command"],
                "all_outcomes":   install_outcomes,
                "hint":           (
                    "Show the user the fix_command verbatim and stop — do "
                    "NOT silently fall back to telling them to install it "
                    "themselves with no context. If reason is "
                    "'no_wheel_for_this_python' the user is on a Python "
                    "version newer than the package supports; suggest "
                    "the alternative listed in tried[]."
                ),
            }
        # Re-check after install
        missing = _missing_modules(imports)
        if missing:
            return {
                "error":         "still_missing_after_install",
                "missing":       missing,
                "all_outcomes":  install_outcomes,
            }
    elif missing and not auto_install:
        return {
            "error":   "missing_modules",
            "missing": missing,
            "hint":    "Re-run with auto_install=true to install via pip.",
        }

    # 2. Spawn — on Windows with CREATE_NEW_CONSOLE so the GUI surfaces;
    # on POSIX, just run normally (X / Wayland / macOS handle window
    # attachment themselves).
    cwd = working_directory or str(script_path.parent)
    cmd = [sys.executable, str(script_path), *(args or [])]
    creationflags = _windows_creationflags() if new_console else 0
    try:
        popen = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    # 3. Wire into the same registry shell_exec uses so the user's Shells
    # panel + shell_get_output() Just Work.
    class _FakeAsyncProc:
        def __init__(self, p): self._p = p; self.returncode = None
        @property
        def pid(self): return self._p.pid
        def kill(self):
            try: self._p.kill()
            except Exception: pass
        async def wait(self):
            return await asyncio.to_thread(self._p.wait)

    fake = _FakeAsyncProc(popen)
    managed = ManagedProcess(pid=popen.pid, command=" ".join(cmd), process=fake)
    ProcessRegistry.register(managed)

    import threading as _t
    def _reader(stream, buf):
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                buf.append(line.rstrip("\r\n"))
        except Exception as exc:
            buf.append(f"[stream reader error: {type(exc).__name__}: {exc}]")

    _t.Thread(target=_reader, args=(popen.stdout, managed.stdout_buf), daemon=True).start()
    _t.Thread(target=_reader, args=(popen.stderr, managed.stderr_buf), daemon=True).start()

    async def _watch():
        rc = await asyncio.to_thread(popen.wait)
        managed.running = False
        managed.exit_code = rc
        fake.returncode = rc
    asyncio.create_task(_watch())

    # 4. Grace window so an immediate crash surfaces NOW.
    await _wait_for_early_exit(managed, grace_seconds=2.0)
    base = {
        "pid":         popen.pid,
        "command":     " ".join(cmd),
        "cwd":         cwd,
        "installed":   installed,        # Distributions actually installed
        "install_log": install_outcomes  # One entry per attempted module
                       if install_outcomes else None,
    }
    if not managed.running:
        return {
            **base,
            "status":       "exited_early",
            "exit_code":    managed.exit_code,
            "stdout":       "\n".join(managed.stdout_buf[-200:]),
            "stderr":       "\n".join(managed.stderr_buf[-200:]),
            "hint":         "Process crashed during startup. Check stderr.",
        }
    return {
        **base,
        "status":       "running",
        "exit_code":    -1,
        "stdout":       "\n".join(managed.stdout_buf[-30:]),
        "stderr":       "\n".join(managed.stderr_buf[-30:]),
        "message": (
            "Desktop process is live. A new console + window should be on "
            "the user's screen. Use shell_get_output(pid) to read further "
            "output, shell_kill(pid) to stop it."
        ),
    }


PYTHON_RUN_TOOL = ToolDefinition(
    name="python_run",
    description=(
        "Run a Python script as a real desktop process — with a new console "
        "window on Windows and auto-installed dependencies. Use this for GUI "
        "/ windowed apps (pygame, tkinter, PySide, kivy). For pure-CLI "
        "scripts use shell_exec instead so the output streams into chat. "
        "Never use app_open(...) to 'run' a Python script — app_open opens "
        "files in their default handler, which on Windows is usually an "
        "editor (Notepad / VS Code), not the interpreter."
    ),
    parameters={
        "type": "object",
        "properties": {
            "script": {
                "type":        "string",
                "description": "Path to a .py file. Relative paths resolve against working_directory.",
            },
            "args": {
                "type":        "array",
                "items":       {"type": "string"},
                "description": "Optional CLI arguments passed to the script.",
            },
            "working_directory": {
                "type":        "string",
                "description": "Working directory. Defaults to the script's parent.",
            },
            "auto_install": {
                "type":        "boolean",
                "description": "When true (default), missing top-level imports are pip-installed before running.",
            },
            "new_console": {
                "type":        "boolean",
                "description": "Windows only — spawn with CREATE_NEW_CONSOLE so GUI windows surface. Default true.",
            },
        },
        "required": ["script"],
    },
    handler=_python_run,
    requires_approval=True,
    approval_message="Run a Python script as a desktop process (may install pip packages)",
    approval_type="confirm",
)
