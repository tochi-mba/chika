"""Two locked-in fixes the user lost progress to:

1. Auto-continue silently failed when the user-visible reply came from
   ``_force_followup`` (the LLM produced text only AFTER its tool calls,
   and ``final_text`` in ``_chat_inner`` stayed empty). Now both the
   main-loop text and the followup text are checked.

2. Plan-update enforcement: when a workflow performs real work but
   doesn't tick the checklist, the next-turn tool result MUST carry a
   plan-nudge reminder so the LLM ticks the box on the very next turn.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

from chika.core.engine import _should_auto_continue
from chika.core.variable_store import VariableStore, VarType


# ── Auto-continue heuristic survives a "Now I'll …" tail ─────────────────

def test_auto_continue_heuristic_matches_followup_style_text():
    """The exact phrasing the agent used in the user's session must trigger."""
    body = (
        "Element interactions module added — fire burns sand into smoke, "
        "water extinguishes fire, fire heats metal to glow.\n\n"
        "Now the system supports realistic reactions between element types.\n"
        "Next, I'll link this interaction logic into the main simulation loop "
        "and proceed to implement density, temperature, and state transitions."
    )
    assert _should_auto_continue(body), (
        "the actual user-session text must trigger — without this the engine "
        "stays put after the agent promises more work"
    )


# ── Engine recursion uses force-followup text when main loop produces nothing

def _build_engine_with_mocked_streams(turns: list[dict]):
    """Build a real engine with both _stream_llm AND _force_followup
    mocked so we can simulate the case where the agent's reply only
    arrives via the forced followup path.

    Each ``turns`` entry is a dict:
    - main:     text yielded by _stream_llm directly (no tool_call)
    - followup: text the force_followup path yields
    """
    from api.session_manager import session_manager
    eng = session_manager.get_or_create("__followup_continue__")
    eng._history = []
    eng._title = ""
    eng._auto_continue_depth = 0
    eng._last_followup_text = ""

    state = {"i": 0}

    async def _fake_stream(self, _messages):
        i = state["i"]
        for tok in (turns[i]["main"] or "").split():
            yield {"type": "token", "text": tok + " "}

    async def _fake_followup(self):
        i = state["i"]
        state["i"] += 1
        text = turns[i]["followup"] or ""
        if text:
            for tok in text.split():
                yield {"type": "token", "text": tok + " "}
            self._history.append({"role": "assistant", "content": text})
        # Mirror the real implementation's exposure of the captured text.
        self._last_followup_text = text

    async def _fake_complete(self, _prompt: str) -> str:
        return "Test Title"

    async def _fake_validate(self, _text: str):
        return None

    eng._stream_llm = _fake_stream.__get__(eng, type(eng))
    eng._force_followup = _fake_followup.__get__(eng, type(eng))
    eng._llm_complete = _fake_complete.__get__(eng, type(eng))
    eng._validate_grounding = _fake_validate.__get__(eng, type(eng))
    return eng


def test_auto_continue_fires_when_text_came_from_force_followup():
    """Main loop produces no tokens (turn 1 ended via forced followup);
    the followup contains a "Next, I'll …" tail. The engine MUST fire
    a continuation despite ``final_text`` being empty in _chat_inner."""
    eng = _build_engine_with_mocked_streams([
        # Turn 1 — main stream is empty, only the forced followup speaks.
        {"main": "", "followup":
            "Step 1 done. Next, I'll start step 2."},
        # Turn 2 — clean wrap so we don't infinite-loop the test.
        {"main": "All done.", "followup": ""},
    ])

    async def _drive():
        return [ev async for ev in eng.chat("kick it off")]

    with patch("api.settings_store.get") as mock_get:
        mock_get.side_effect = lambda k, default=None: {
            "auto_continue": "on", "auto_continue_max": 5,
        }.get(k, default)
        events = asyncio.run(_drive())

    types = [e.get("type") for e in events]
    assert types.count("auto_continue") == 1, (
        f"force_followup text must trigger auto-continue, got types: {types}"
    )


# ── Plan nudge: real work without plan_update → reminder injected ─────────

def _engine_with_plan(in_progress_id: str, in_progress_text: str):
    """Return an engine with a plan that has one in_progress task."""
    from api.session_manager import session_manager
    eng = session_manager.get_or_create("__plan_nudge__")
    eng._vars.set("plan", {
        "tasks": [
            {"id": in_progress_id, "text": in_progress_text,
             "status": "in_progress"},
            {"id": "t2", "text": "next task", "status": "pending"},
        ],
        "created_at": time.time(),
        "updated_at": time.time(),
    }, VarType.JSON, source="plan:set")
    return eng


def test_plan_nudge_fires_when_write_tool_used_without_plan_touch():
    """file_write + no plan_update → reminder string injected."""
    eng = _engine_with_plan("t1", "Build the engine core")
    nudge = eng._build_plan_nudge(["file_write", "shell_exec"],
                                   plan_touched=False)
    assert nudge is not None
    assert "PLAN NUDGE" in nudge
    assert "t1" in nudge
    # The reminder must reference the tool that was actually used
    # (so the LLM can see we noticed it did real work).
    assert "file_write" in nudge or "shell_exec" in nudge


def test_plan_nudge_suppressed_when_plan_was_touched():
    """If the workflow already called plan_update, no nudge."""
    eng = _engine_with_plan("t1", "Build the engine core")
    nudge = eng._build_plan_nudge(["file_write", "plan_update"],
                                   plan_touched=True)
    assert nudge is None


def test_plan_nudge_suppressed_when_no_in_progress_task():
    """If the plan exists but every task is done, no nudge — there's
    nothing to tick off."""
    from api.session_manager import session_manager
    eng = session_manager.get_or_create("__plan_nudge_no_in_progress__")
    eng._vars.set("plan", {
        "tasks": [
            {"id": "t1", "text": "x", "status": "done"},
        ],
    }, VarType.JSON, source="plan:set")
    nudge = eng._build_plan_nudge(["file_write"], plan_touched=False)
    assert nudge is None


def test_plan_nudge_suppressed_for_read_only_workflows():
    """A workflow that only ran file_read / git_status / etc. (no writes)
    shouldn't trigger the nudge."""
    eng = _engine_with_plan("t1", "Investigate the bug")
    nudge = eng._build_plan_nudge(["file_read", "git_status", "git_diff"],
                                   plan_touched=False)
    assert nudge is None


def test_plan_nudge_suppressed_when_no_plan_active():
    """No plan set yet → no nudge (the agent might be doing one-shot work)."""
    from api.session_manager import session_manager
    eng = session_manager.get_or_create("__plan_nudge_no_plan__")
    # Make sure no plan is set
    eng._vars.delete("plan")
    nudge = eng._build_plan_nudge(["file_write"], plan_touched=False)
    assert nudge is None
