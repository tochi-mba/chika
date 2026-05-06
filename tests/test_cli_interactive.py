"""Coverage for chika/_cli/interactive.py — approval + question handlers."""
from __future__ import annotations

from collections import deque
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from chika._cli import interactive as ci


# ── _is_tty ────────────────────────────────────────────────────────────


def test_is_tty_returns_bool():
    """Whatever the actual env, _is_tty() returns a bool — never raises."""
    out = ci._is_tty()
    assert isinstance(out, bool)


# ── _prompt ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_returns_user_input():
    """_prompt wraps input() in a worker thread; mocking input is enough."""
    with patch("builtins.input", return_value="hello"):
        out = await ci._prompt("> ")
    assert out == "hello"


@pytest.mark.asyncio
async def test_prompt_returns_empty_on_eof():
    """EOFError → empty string (no exception bubbles up)."""
    with patch("builtins.input", side_effect=EOFError()):
        out = await ci._prompt("> ")
    assert out == ""


@pytest.mark.asyncio
async def test_prompt_returns_empty_on_ctrl_c():
    """KeyboardInterrupt → empty string."""
    with patch("builtins.input", side_effect=KeyboardInterrupt()):
        out = await ci._prompt("> ")
    assert out == ""


# ── _prompt_yes_no ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_yes_no_y_returns_true():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(return_value="y")):
        out = await ci._prompt_yes_no(console)
    assert out is True


@pytest.mark.asyncio
async def test_prompt_yes_no_yes_returns_true():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(return_value="YES")):
        out = await ci._prompt_yes_no(console)
    assert out is True


@pytest.mark.asyncio
async def test_prompt_yes_no_n_returns_false():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(return_value="n")):
        out = await ci._prompt_yes_no(console)
    assert out is False


@pytest.mark.asyncio
async def test_prompt_yes_no_re_asks_on_invalid_input():
    """Invalid → re-prompts until valid."""
    responses = deque(["maybe", "y"])
    console = Console(file=StringIO(), force_terminal=False)

    async def fake(_):
        return responses.popleft()

    with patch.object(ci, "_prompt", fake):
        out = await ci._prompt_yes_no(console)
    assert out is True
    assert not responses  # both responses consumed


# ── _prompt_workspace_scope ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_workspace_session():
    console = Console(file=StringIO(), force_terminal=False)
    args = {"path": "/etc/foo", "scope_dir": "/etc"}
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["s"])):
        out = await ci._prompt_workspace_scope(console, args)
    assert out["scope"] == "session"


@pytest.mark.asyncio
async def test_prompt_workspace_once():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["o"])):
        out = await ci._prompt_workspace_scope(console, {})
    assert out["scope"] == "once"


@pytest.mark.asyncio
async def test_prompt_workspace_deny_with_reason():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["n", "outside workspace"])):
        out = await ci._prompt_workspace_scope(console, {})
    assert out["scope"] == "deny"
    assert "outside workspace" in out["reason"]


# ── _prompt_plan_review ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_plan_review_approve():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["a"])):
        out = await ci._prompt_plan_review(console)
    assert out["action"] == "approve"


@pytest.mark.asyncio
async def test_prompt_plan_review_edit_with_feedback():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["e", "use TS"])):
        out = await ci._prompt_plan_review(console)
    assert out["action"] == "edit"
    assert out["feedback"] == "use TS"


@pytest.mark.asyncio
async def test_prompt_plan_review_deny_with_reason():
    console = Console(file=StringIO(), force_terminal=False)
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["d", "wrong stack"])):
        out = await ci._prompt_plan_review(console)
    assert out["action"] == "deny"
    assert out["reason"] == "wrong stack"


# ── make_approval_handler ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_handler_confirm_path():
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_approval_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(return_value="y")):
        out = await handler(
            request_id="r1", tool_name="shell_exec",
            args={"command": "ls"},
            message="Run ls?",
            approval_type="confirm",
        )
    assert out is True


@pytest.mark.asyncio
async def test_approval_handler_workspace_path():
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_approval_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(return_value="o")):
        out = await handler(
            request_id="r2", tool_name="file_write",
            args={"path": "/tmp/x", "scope_dir": "/tmp"},
            message="Write outside workspace?",
            approval_type="workspace_scope",
        )
    assert out["scope"] == "once"


@pytest.mark.asyncio
async def test_approval_handler_plan_review_path():
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_approval_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(return_value="a")):
        out = await handler(
            request_id="r3", tool_name="plan_review",
            args={}, message="Approve plan?",
            approval_type="plan_review",
        )
    assert out["action"] == "approve"


@pytest.mark.asyncio
async def test_approval_handler_unknown_type_falls_back_to_yn():
    """Unknown approval_type values fall back to y/n."""
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_approval_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(return_value="n")):
        out = await handler(
            request_id="r4", tool_name="?",
            args={}, message="?", approval_type="unknown_type",
        )
    assert out is False


@pytest.mark.asyncio
async def test_approval_handler_pauses_live_region_when_renderer_passed():
    """If a renderer with _live is passed, the handler stops it during prompts."""
    console = Console(file=StringIO(), force_terminal=False)

    class FakeRenderer:
        def __init__(self):
            self._live = object()
            self._stopped = False
            self._restarted = False
        def _stop_live(self):
            self._stopped = True
            self._live = None
        def _ensure_live(self, view):
            self._restarted = True
        def _render_view(self):
            return "view"

    rdr = FakeRenderer()
    handler = ci.make_approval_handler(console, renderer=rdr)
    with patch.object(ci, "_prompt", AsyncMock(return_value="y")):
        await handler(
            request_id="r5", tool_name="t", args={}, message="?",
            approval_type="confirm",
        )
    assert rdr._stopped is True
    assert rdr._restarted is True


# ── make_question_handler ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_question_handler_single_choice_picks_by_index():
    """User types '2' → picks the 2nd option."""
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_question_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["2", ""])):
        out = await handler(
            request_id="q1",
            question="Which framework?",
            options=[{"label": "React"}, {"label": "Vue"}, {"label": "Svelte"}],
            multi_select=False,
        )
    assert out["choice"] == "Vue"
    assert out["choice_index"] == 1


@pytest.mark.asyncio
async def test_question_handler_free_text_input_becomes_notes():
    """Non-numeric input is treated as a note rather than a pick."""
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_question_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(return_value="actually a note")):
        out = await handler(
            request_id="q2",
            question="Pick",
            options=[{"label": "A"}, {"label": "B"}],
            multi_select=False,
        )
    assert out["notes"] == "actually a note"
    assert out["choice"] == ""
    assert out["choice_index"] == -1


@pytest.mark.asyncio
async def test_question_handler_re_asks_on_out_of_range_index():
    """Index outside 1..N re-prompts until valid."""
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_question_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(side_effect=["99", "1", ""])):
        out = await handler(
            request_id="q3",
            question="Pick",
            options=[{"label": "A"}, {"label": "B"}],
            multi_select=False,
        )
    assert out["choice"] == "A"


@pytest.mark.asyncio
async def test_question_handler_options_can_be_plain_strings():
    """Options as raw strings (not dicts) also work."""
    console = Console(file=StringIO(), force_terminal=False)
    handler = ci.make_question_handler(console)
    with patch.object(ci, "_prompt", AsyncMock(return_value="1")):
        out = await handler(
            request_id="q4",
            question="Pick",
            options=["one", "two"],
            multi_select=False,
        )
    assert out["choice"] == "one"
