"""shell_skill — wraps the shell tools + contributes a per-turn block
listing the agent's currently-running background processes.

The five shell tools (``shell_exec`` / ``shell_get_output`` /
``shell_kill`` / ``shell_list_processes`` / ``shell_wait``) used to be
loose ToolDefinition objects registered directly. Bundling them into a
Skill lets us own the dynamic "ACTIVE SHELLS" block as a
``prompt_section`` contributor instead of hard-coding it in
PromptBuilder. Same artwork the agent already saw, now sourced from the
right place.
"""
from __future__ import annotations

from chika.core.skill_registry import Skill
from chika.tools.shell_tool import ALL_SHELL_TOOLS, ProcessRegistry


def _render_active_shells_block() -> str:
    """Return a short markdown block describing every tracked process.

    Empty string when nothing is running — the prompt builder skips
    blank contributions so we don't pay for a "no shells" header on
    every turn.
    """
    procs = ProcessRegistry.all() or []
    if not procs:
        return ""
    lines: list[str] = ["## Active background shells", ""]
    for p in procs:
        pid = p.get("pid")
        cmd = (p.get("command") or "").strip()
        if len(cmd) > 120:
            cmd = cmd[:120] + "…"
        if p.get("running"):
            lines.append(f"- `pid {pid}` running — `{cmd}`")
        else:
            lines.append(
                f"- `pid {pid}` exited (code {p.get('exit_code')}) — `{cmd}`"
            )
    lines.append("")
    lines.append(
        "Use `shell_kill(pid)` to terminate a runaway. "
        "`shell_get_output(pid)` reads buffered output. "
        "`shell_wait(pid)` blocks until done."
    )
    return "\n".join(lines)


def build_shell_skill() -> Skill:
    """Build the shell skill — same tools, plus the dynamic prompt
    section so the agent always sees what it has spawned."""
    return Skill(
        name="shell",
        description=(
            "Run shell commands and manage background processes. "
            "Foreground (default): blocks, returns stdout/stderr/exit. "
            "Background: returns a pid; query it with shell_get_output / "
            "shell_wait, terminate with shell_kill."
        ),
        tools=list(ALL_SHELL_TOOLS),
        prompt_section=_render_active_shells_block,
        workflow_examples="",
    )
