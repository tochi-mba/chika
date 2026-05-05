"""CLI handlers for the engine's interactive channels.

The web-app (api/server.py) wires ``approval_handler`` and
``question_handler`` to a WebSocket so the frontend can show modals.
The CLI never had its own equivalents, which broke three flows:

- ``ask_user`` (question_skill) — returned ``no_question_handler``
- workspace-scope writes — silently auto-granted because no handler
- the new plan-approval gate — silently no-op'd

This module supplies CLI-native versions: numbered prompts for
multiple-choice questions, y/n + free-text for approvals, and the
tri-state session/once/deny picker for workspace scope. Each function
matches the shape the engine expects so the same skill code paths
work whether the user is in a browser or the terminal.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Awaitable, Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from chika._cli.renderer import THEME


# ── Helpers ────────────────────────────────────────────────────────────


async def _prompt(prompt_text: str) -> str:
    """Read one line from stdin without blocking the asyncio loop.

    Blocking ``input()`` runs on a worker thread so the engine can keep
    streaming events on the main task. Returns "" on EOF / Ctrl-C.
    """
    try:
        return await asyncio.to_thread(input, prompt_text)
    except (EOFError, KeyboardInterrupt):
        return ""


def _is_tty() -> bool:
    """True when stdin/stdout are real TTYs.

    The handlers are useless under piped stdin (no human to ask), so
    callers check this before wiring. Tests exercise the engine
    directly without these handlers.
    """
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


# ── Approval handler ───────────────────────────────────────────────────


def make_approval_handler(
    console: Console, renderer=None,
) -> Callable[..., Awaitable]:
    """Build an approval handler that prints a panel + prompts the user.

    The CLI renderer keeps a ``rich.Live`` region open across the
    bottom of the terminal during a turn (animated pet + spinner). If
    we ``console.print`` and ``input()`` while that's open, the panel
    is invisible behind the live region and the prompt cursor renders
    over the pet animation. ``renderer`` (optional) lets us stop the
    Live region before the prompt and restart it after — so the panel
    lands in scrollback and the prompt has the terminal to itself.

    Handles four ``approval_type`` shapes the engine emits:

    - ``confirm``        — y/n  → bool
    - ``workspace_scope``— s/o/n + reason → ``{scope, reason}``
    - ``plan_review``    — a/e/d + feedback → ``{action, feedback, reason}``
    - everything else    — falls back to y/n
    """

    async def handler(
        request_id: str,
        tool_name: str,
        args: dict,
        step_id: str = "",
        message: str = "",
        approval_type: str = "confirm",
    ):
        # Pause the Live region (if any) so console.print + input can
        # share the terminal cleanly with the user.
        was_live = False
        if renderer is not None and getattr(renderer, "_live", None) is not None:
            try:
                renderer._stop_live()
                was_live = True
            except Exception:
                pass

        try:
            # Always paint a header so the user sees what they're approving.
            title = {
                "workspace_scope": " 📁 Write outside workspace?",
                "plan_review":     " 📋 Approve this plan?",
                "verify_password": " 🔐 Password required",
                "set_password":    " 🔑 Set password",
            }.get(approval_type, " ⚠ Approval required")
            console.print(Panel(
                Text(message or f"Run {tool_name}?", style=THEME.text),
                title=Text(title, style=f"bold {THEME.accent}"),
                title_align="left",
                border_style=THEME.accent,
                padding=(1, 2),
                expand=False,
            ))

            if approval_type == "workspace_scope":
                return await _prompt_workspace_scope(console, args)
            if approval_type == "plan_review":
                return await _prompt_plan_review(console)
            return await _prompt_yes_no(console)
        finally:
            # Restart the Live region so the rest of the turn keeps
            # animating beneath subsequent tool results.
            if was_live and renderer is not None:
                try:
                    renderer._ensure_live(renderer._render_view())
                except Exception:
                    pass

    return handler


async def _prompt_yes_no(console: Console) -> bool:
    while True:
        ans = (await _prompt("  Approve? [y/N]: ")).strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no", "", "q"):
            return False
        console.print(Text("  · Type y or n.", style=THEME.dim))


async def _prompt_workspace_scope(console: Console, args: dict) -> dict:
    """``[s]ession allow / [o]nce / [n]o (deny + optional reason)``"""
    path = args.get("path") or ""
    if path:
        console.print(Text(f"  target: {path}", style=THEME.dim))
    while True:
        raw = (await _prompt(
            "  Allow [s]ession (this folder forever) / [o]nce / [n]o: ",
        )).strip().lower()
        if raw in ("s", "session"):
            return {"scope": "session"}
        if raw in ("o", "once"):
            return {"scope": "once"}
        if raw in ("n", "no", "deny", "q", ""):
            reason = (await _prompt(
                "  Reason (optional, blank to skip): ",
            )).strip()
            return {"scope": "deny", "reason": reason}
        console.print(Text("  · Type s, o, or n.", style=THEME.dim))


async def _prompt_plan_review(console: Console) -> dict:
    """``[a]pprove / [e]dit feedback / [d]eny reason``"""
    while True:
        raw = (await _prompt(
            "  [a]pprove / [e]dit (with feedback) / [d]eny (with reason): ",
        )).strip().lower()
        if raw in ("a", "approve", "y", "yes"):
            return {"action": "approve"}
        if raw in ("e", "edit"):
            feedback = (await _prompt(
                "  Feedback for the edit (one line): ",
            )).strip()
            if not feedback:
                console.print(Text(
                    "  · feedback was empty — treating as approve",
                    style=THEME.warn,
                ))
                return {"action": "approve"}
            return {"action": "edit", "feedback": feedback}
        if raw in ("d", "deny", "n", "no", "reject"):
            reason = (await _prompt(
                "  Reason (one line): ",
            )).strip()
            return {"action": "deny", "reason": reason}
        console.print(Text("  · Type a, e, or d.", style=THEME.dim))


# ── Question handler ───────────────────────────────────────────────────


def make_question_handler(
    console: Console, renderer=None,
) -> Callable[..., Awaitable[dict]]:
    """Build a question handler that prints a numbered menu + reads a
    choice. Handles single-select today; multi-select left for a later
    iteration since the engine paths that need it are WS-only.

    Like the approval handler, the optional ``renderer`` lets us pause
    the Live region while the menu + prompt have the terminal.
    """

    async def handler(
        *,
        request_id: str,
        question: str,
        options: list,
        header: str = "",
        multi_select: bool = False,
    ) -> dict:
        was_live = False
        if renderer is not None and getattr(renderer, "_live", None) is not None:
            try:
                renderer._stop_live()
                was_live = True
            except Exception:
                pass
        try:
            title = " ❓ " + (header or "Question")
            body_lines = [question.strip()]
            for i, opt in enumerate(options, start=1):
                label = opt.get("label", "") if isinstance(opt, dict) else str(opt)
                desc = opt.get("description", "") if isinstance(opt, dict) else ""
                body_lines.append(f"  {i}. {label}")
                if desc:
                    body_lines.append(f"     {desc}")
            console.print(Panel(
                Text("\n".join(body_lines), style=THEME.text),
                title=Text(title, style=f"bold {THEME.accent}"),
                title_align="left",
                border_style=THEME.accent,
                padding=(1, 2),
                expand=False,
            ))

            # Single-select for now — multi can come later.
            while True:
                raw = (await _prompt(
                    f"  Pick 1-{len(options)} (or text to add a note): ",
                )).strip()
                if not raw:
                    console.print(Text("  · pick a number.", style=THEME.dim))
                    continue
                if raw.isdigit():
                    idx = int(raw) - 1
                    if 0 <= idx < len(options):
                        opt = options[idx]
                        label = (opt.get("label", "") if isinstance(opt, dict)
                                 else str(opt))
                        return {
                            "choice":         label,
                            "choice_index":   idx,
                            "choices":        [label],
                            "choice_indices": [idx],
                            "notes":          "",
                        }
                    console.print(Text(
                        f"  · {raw} is out of range.", style=THEME.dim,
                    ))
                    continue
                # Free-text answer: treat as notes against option 1.
                return {
                    "choice":         "",
                    "choice_index":   -1,
                    "choices":        [],
                    "choice_indices": [],
                    "notes":          raw,
                }
        finally:
            if was_live and renderer is not None:
                try:
                    renderer._ensure_live(renderer._render_view())
                except Exception:
                    pass

    return handler
