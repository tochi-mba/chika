"""The CLI Renderer must show a live "running" indicator while a tool is
in flight. This test pins the state machine that drives it.

Renders directly against the Renderer (no Live opened) by exercising the
event handlers and inspecting ``_running_tool``. The visual shape is
covered by the smoke run; this guards the bookkeeping.
"""
from __future__ import annotations

import time

from rich.console import Console

from chika._cli.pets import get as get_pet
from chika._cli.renderer import Renderer


def _make_renderer():
    # Console with no width so soft_wrap doesn't matter.
    return Renderer(console=Console(highlight=False, soft_wrap=True),
                    pet=get_pet("cat"))


def test_tool_call_sets_running_indicator():
    r = _make_renderer()
    r._on_tool_call({
        "type": "tool_call", "step_id": "s1",
        "tool": "scaffold_web_app",
        "args": {"stack": "p5", "name": "demo"},
    })
    assert r._running_tool is not None
    assert r._running_tool["tool"] == "scaffold_web_app"
    assert r._running_tool["step_id"] == "s1"
    assert isinstance(r._running_tool["started_at"], float)
    # A non-empty hint is set so the user sees plain English alongside the tool name.
    assert r._running_tool.get("hint")  # _TOOL_BUBBLES has a row for scaffold_web_app or default fallback


def test_matching_tool_result_clears_indicator():
    r = _make_renderer()
    r._on_tool_call({
        "type": "tool_call", "step_id": "s1", "tool": "shell_exec", "args": {},
    })
    assert r._running_tool is not None
    r._on_tool_result({
        "type": "tool_result", "step_id": "s1", "tool": "shell_exec",
        "result": {"stdout": "ok"}, "error": None, "duration_ms": 10,
    })
    assert r._running_tool is None


def test_mismatched_tool_result_does_not_clear():
    """A tool_result for a DIFFERENT step_id must not clobber the in-flight
    indicator (matters for parallel workflows)."""
    r = _make_renderer()
    r._on_tool_call({
        "type": "tool_call", "step_id": "s1", "tool": "web_fetch", "args": {},
    })
    r._on_tool_result({
        "type": "tool_result", "step_id": "s99", "tool": "web_fetch",
        "result": {}, "error": None, "duration_ms": 5,
    })
    assert r._running_tool is not None, (
        "result for unrelated step_id must not clear the active indicator"
    )


def test_end_turn_clears_stale_indicator():
    r = _make_renderer()
    r.start_turn()
    r._on_tool_call({
        "type": "tool_call", "step_id": "s1", "tool": "shell_exec", "args": {},
    })
    # Simulate the engine bailing out before sending tool_result.
    r.end_turn()
    assert r._running_tool is None, (
        "end_turn must clear stale spinner state so it doesn't bleed "
        "into the next prompt"
    )


def test_running_indicator_renderable_includes_elapsed_time():
    r = _make_renderer()
    r._on_tool_call({
        "type": "tool_call", "step_id": "s1", "tool": "shell_exec", "args": {},
    })
    # Backdate the start time so we can assert on a non-zero elapsed.
    r._running_tool["started_at"] = time.time() - 2.5
    rendered = r._render_running_tool_row()
    assert rendered is not None
    plain = rendered.plain
    assert "shell_exec" in plain
    # Should contain something like "2.5s" or "2.6s" — formatted seconds.
    assert "s" in plain
    # An elapsed approximation, allowing for drift up to a few hundred ms.
    assert any(s in plain for s in ("2.4s", "2.5s", "2.6s", "2.7s")), (
        f"expected elapsed ~2.5s in {plain!r}"
    )


def test_running_indicator_returns_none_when_idle():
    r = _make_renderer()
    assert r._render_running_tool_row() is None
