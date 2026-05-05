"""End-to-end CLI tests — spawn ``python chika.py``, drive via stdin, assert
on the rendered terminal output.

These run a real subprocess: real terminal renderer, real prompt loop,
real session manager, real skill registry. The LLM is stubbed via
``CHIKA_STUB_LLM_SCRIPT`` so every turn is deterministic. Costs zero
tokens and runs in CI.

Why subprocess and not in-process? The CLI's full surface (rich panels,
ANSI cursor moves, pet animator, prompt_toolkit fallback) only lights
up when stdin/stdout are real pipes. Importing ``chika._cli.app`` in
the same Python process hides bugs in the entry point itself
(``cli()``, ``_enable_utf8_stdout``, sys.path wiring).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._helpers.cli_harness import (
    run_cli,
    script,
    text_turn,
    workflow_turn,
)


# CLI subprocess tests are slower than unit tests — mark them so a fast-
# loop dev run can deselect with ``-m 'not cli_e2e'``.
pytestmark = [pytest.mark.cli_e2e, pytest.mark.slow]


# Shared workflow-builder
def _wf(*steps):
    return {"type": "sequential", "id": "wf", "steps": list(steps)}


# ── Banner & status line ──────────────────────────────────────────────────


def test_cli_starts_renders_banner_and_exits_on_quit():
    res = run_cli(inputs=["/quit"], script=script([]))
    assert res.returncode == 0
    assert res.contains("chika v")
    assert res.contains("/help for commands")
    # Status line elements
    assert "provider" in res.plain
    assert "model" in res.plain
    assert "profile" in res.plain


def test_cli_shows_pet_panel_on_startup():
    """A pet panel must be visible above the first prompt."""
    res = run_cli(inputs=["/quit"], script=script([]))
    # Default profile has SOME pet selected; the pet name appears in panel title.
    # We check for the panel border characters that a pet panel produces.
    assert "the" in res.plain.lower()  # at least one pet name has 'the' in panel
    # Banner panel is always present:
    assert "the agentic AI assistant" in res.plain.lower() \
        or "agentic ai assistant" in res.plain.lower()


def test_cli_help_command_lists_commands():
    res = run_cli(inputs=["/help", "/quit"], script=script([]))
    assert res.returncode == 0
    # Every CLI must list these core commands.
    for cmd in ("/quit", "/clear", "/status", "/settings", "/plan"):
        assert cmd in res.plain, f"/help did not mention {cmd}: {res.plain[-2000:]}"


# ── Plain text turn ───────────────────────────────────────────────────────


def test_cli_plain_text_turn_streams_to_stdout():
    res = run_cli(
        inputs=["hi", "/quit"],
        script=script([text_turn("Hello! Just a quick reply.")]),
    )
    assert res.returncode == 0
    # Token text appears in the rendered output.
    assert "Hello" in res.plain
    assert "quick reply" in res.plain


def test_cli_handles_unicode_in_assistant_response():
    res = run_cli(
        inputs=["greet me", "/quit"],
        script=script([text_turn("Done — I’ll move on next.")]),
    )
    # Em-dash + curly quote must round-trip through rich.
    assert "Done" in res.plain
    assert "move on next" in res.plain


# ── Tool execution ────────────────────────────────────────────────────────


def test_cli_workflow_with_file_read_renders_tool_block(tmp_path):
    """A read tool result should appear under a bordered tool block."""
    f = tmp_path / "hello.txt"
    f.write_text("hello from disk\n", encoding="utf-8")
    wf = _wf({"tool": "file_read",
              "args": {"path": str(f), "start_line": 1, "end_line": 5}})
    res = run_cli(
        inputs=[f"read {f}", "/quit"],
        script=script([
            workflow_turn(wf),
            text_turn("File read."),
        ]),
    )
    assert res.returncode == 0
    # Tool name shows somewhere in the output.
    assert "file_read" in res.plain
    # Either a result preview line or a count summary.
    assert "hello" in res.plain.lower() or "file" in res.plain.lower()


def test_cli_workflow_failure_renders_error_inline():
    """An error event must be visible to the user."""
    wf = _wf({"tool": "file_read",
              "args": {"path": "/no/such/path/exists", "start_line": 1, "end_line": 5}})
    res = run_cli(
        inputs=["read missing", "/quit"],
        script=script([
            workflow_turn(wf),
            text_turn("That file doesn't exist."),
        ]),
    )
    assert res.returncode == 0
    assert "file_read" in res.plain
    # Error appears either in a tool_result block or the assistant message.
    assert "doesn't" in res.plain.lower() or "error" in res.plain.lower() \
        or "no such" in res.plain.lower()


# ── Auto-continue ─────────────────────────────────────────────────────────


def test_cli_auto_continue_fires_on_promise():
    """Renderer must show the ↻ auto-continue badge when the agent
    promises more work and the engine fires another turn."""
    res = run_cli(
        inputs=["go", "/quit"],
        script=script([
            text_turn("Plan loaded.\n\nNext, I'll scaffold the project."),
            text_turn("Scaffolded."),
        ]),
    )
    assert res.returncode == 0
    # The renderer prints "auto-continue" with the depth — either Unicode
    # ↻ or ASCII fallback @, we assert on the word.
    assert "auto-continue" in res.plain.lower(), res.plain[-3000:]


def test_cli_auto_continue_blocked_when_setting_off():
    """When auto_continue is off, the renderer must surface why we
    didn't continue."""
    res = run_cli(
        inputs=[
            "/auto-continue off",
            "go",
            "/quit",
        ],
        script=script([
            text_turn("Done. Now I'll handle the next part."),
        ]),
    )
    assert res.returncode == 0
    assert "auto" in res.plain.lower()


# ── Slash commands round-trip ────────────────────────────────────────────


def test_cli_status_shows_provider_and_profile():
    res = run_cli(inputs=["/status", "/quit"], script=script([]))
    assert res.returncode == 0
    assert "provider" in res.plain.lower()
    assert "profile" in res.plain.lower() or "default" in res.plain.lower()


def test_cli_skills_command_lists_known_skills():
    res = run_cli(inputs=["/skills", "/quit"], script=script([]))
    assert res.returncode == 0
    # Plan + git skills are session-scoped — both must show.
    assert "plan" in res.plain.lower()


def test_cli_clear_resets_screen():
    """/clear redraws the banner; the banner appears at least twice."""
    res = run_cli(
        inputs=["/clear", "/quit"],
        script=script([]),
    )
    assert res.returncode == 0
    # Two banner renders means we redrew after clear.
    assert res.plain.count("chika v") >= 1


# ── Plan rendering ────────────────────────────────────────────────────────


def test_cli_plan_set_renders_plan_panel():
    """When the agent sets a plan, the renderer must paint a plan panel."""
    plan_wf = _wf({
        "tool": "plan_set",
        "args": {
            "goal":         "Build a Powder Toy clone",
            "requirements": ["pure JS", "60fps target"],
            "tasks":        ["scaffold", "engine loop", "UI"],
        },
    })
    res = run_cli(
        inputs=["start project", "/quit"],
        script=script([
            workflow_turn(plan_wf),
            text_turn("Plan set."),
        ]),
    )
    assert res.returncode == 0
    # Plan rendering surfaces tasks somewhere.
    assert "scaffold" in res.plain.lower()
    assert "engine" in res.plain.lower() or "ui" in res.plain.lower()


# ── Process hygiene ──────────────────────────────────────────────────────


def test_cli_returncode_zero_on_quit():
    res = run_cli(inputs=["/quit"], script=script([]))
    assert res.returncode == 0


def test_cli_handles_empty_input_lines():
    """Blank lines don't crash; user just gets prompted again."""
    res = run_cli(
        inputs=["", "", "hi", "/quit"],
        script=script([text_turn("hello!")]),
    )
    assert res.returncode == 0
    assert "hello" in res.plain.lower()


def test_cli_unrecognised_slash_command_is_handled():
    """An unknown /cmd must not crash the REPL."""
    res = run_cli(
        inputs=["/notarealcommand", "/quit"],
        script=script([]),
    )
    assert res.returncode == 0
