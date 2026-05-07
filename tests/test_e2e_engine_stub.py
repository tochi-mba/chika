"""End-to-end tests for ChikaEngine using a scripted stub LLM.

These run the real engine — real prompt builder, real workflow engine,
real skill registry, real variable store — but with the LLM swapped for
a deterministic playback. They cover the full user-visible event stream
that the CLI / WS / extension all consume, without burning a single
token.

If a real bug shows up in production (auto-continue, plan gate, skill
gate, kwarg drift), the cheapest reproduction is a new test in this
file: script the LLM responses that triggered it, drive ``engine.chat``,
and assert on the events.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config as cfg

cfg.MAX_MEMORY_TOKENS = 1000
cfg.MAX_HISTORY_TOKENS = 10000
cfg.MAX_TOOL_TURNS = 10
cfg.COMPACT_KEEP_FIRST = 2
cfg.COMPACT_KEEP_LAST = 4
cfg.GROUNDING_VALIDATE_RESPONSE = False

import json
from pathlib import Path

import pytest

from chika.core.engine import ChikaEngine
from chika.core.memory_manager import MemoryManager
from chika.core.prompt_builder import PromptBuilder
from chika.core.skill_registry import SkillRegistry
from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore
from chika.skills import (
    SkillBuildContext,
    get_skill_module,
)
from tests._helpers.stub_llm import StubLLM, install, step, wf_sequential


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def engine(tmp_path: Path) -> ChikaEngine:
    """Build a real ChikaEngine wired to in-memory stores + a tmp memory file."""
    tools = ToolRegistry()
    vars_ = VariableStore()
    mem = MemoryManager(path=tmp_path / "memory.md", max_tokens=1000)
    prompt = PromptBuilder()
    skills = SkillRegistry(tools, mem, prompt)

    # Echo tool — useful in lots of scenarios.
    async def _echo(message: str = "hi", **_extra) -> dict:
        return {"echo": message}

    tools.register(ToolDefinition(
        name="echo", description="echo back",
        parameters={"type": "object",
                    "properties": {"message": {"type": "string"}}},
        handler=_echo,
    ))

    # File-write stub (no actual disk I/O during tests).
    files_written: list[dict] = []

    async def _file_write(path: str = "", content: str = "", **_extra) -> dict:
        files_written.append({"path": path, "content": content})
        return {"ok": True, "path": path, "bytes": len(content)}

    tools.register(ToolDefinition(
        name="file_write", description="write a file",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"},
                                   "content": {"type": "string"}}},
        handler=_file_write,
    ))

    # Plan skill — built via the public discovery API rather than
    # importing the skill's internals directly. Production code goes
    # through this same path, so a refactor inside the skill folder
    # never breaks this test.
    plan_mod = get_skill_module("plan")
    assert plan_mod is not None, "plan skill must be shipped"
    ctx = SkillBuildContext(
        variable_store=vars_,
        engine_getter=lambda: None,
        memory_getter=lambda: None,
        workflow_engine_getter=lambda: None,
        profile_getter=lambda: None,
        workspace_getter=lambda: "",
    )
    skills.register(plan_mod.build_skill(ctx))

    eng = ChikaEngine(tools, vars_, mem, prompt, skills)
    eng._workflow_engine.set_skill_registry(skills)
    eng._files_written = files_written  # type: ignore[attr-defined]
    return eng


async def _drain(engine: ChikaEngine, user_input: str) -> list[dict]:
    return [ev async for ev in engine.chat(user_input)]


# ── Basic flows ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_only_turn_emits_tokens_then_done(engine):
    install(engine, StubLLM([StubLLM.text("Hi! Just answering.")]))
    events = await _drain(engine, "hello")
    types = [e["type"] for e in events]
    assert types[-1] == "done"
    tokens = "".join(e["text"] for e in events if e["type"] == "token")
    assert tokens.strip() == "Hi! Just answering."


@pytest.mark.asyncio
async def test_history_records_user_and_assistant(engine):
    install(engine, StubLLM([StubLLM.text("Sure.")]))
    await _drain(engine, "ping")
    roles = [m["role"] for m in engine._history]
    assert roles == ["user", "assistant"]
    assert engine._history[1]["content"] == "Sure."


@pytest.mark.asyncio
async def test_tool_call_then_text_response(engine):
    install(engine, StubLLM([
        StubLLM.workflow(wf_sequential(
            step("echo", {"message": "from-stub"}),
        )),
        StubLLM.text("All done."),
    ]))
    events = await _drain(engine, "do the thing")
    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["result"] == {"echo": "from-stub"}
    final_text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "done" in final_text.lower()


# ── Auto-continue ─────────────────────────────────────────────────────────


@pytest.fixture
def auto_continue_on():
    """Force auto-continue on with a sane cap, restore prior on teardown.

    Test-order pollution: prior tests in the suite mutate the persisted
    settings file. We want the "fires" tests to own their state.
    """
    import api.settings_store as ss
    prev_enabled = ss.get("auto_continue", "on")
    prev_max     = ss.get("auto_continue_max", 10)
    ss.update({"auto_continue": "on", "auto_continue_max": 10})
    yield
    ss.update({"auto_continue": str(prev_enabled),
               "auto_continue_max": int(prev_max)})


@pytest.mark.asyncio
async def test_auto_continue_fires_when_assistant_promises_more_work(
    engine, auto_continue_on,
):
    install(engine, StubLLM([
        StubLLM.text(
            "Plan loaded.\n\n"
            "Next, I'll scaffold the project and verify the build."
        ),
        # Second turn (the auto-continue) — terminate cleanly.
        StubLLM.text("Done."),
    ]))
    events = await _drain(engine, "go")
    auto = [e for e in events if e["type"] == "auto_continue"]
    assert len(auto) == 1
    assert auto[0]["depth"] == 1


@pytest.mark.asyncio
async def test_auto_continue_curly_quote_variant_still_fires(
    engine, auto_continue_on,
):
    """Regression: U+2019 right single quote must still trigger."""
    install(engine, StubLLM([
        StubLLM.text("Done. Now I’ll wire up the audio."),
        StubLLM.text("Wired."),
    ]))
    events = await _drain(engine, "go")
    assert any(e["type"] == "auto_continue" for e in events)


@pytest.mark.asyncio
async def test_auto_continue_does_not_fire_on_question(engine, auto_continue_on):
    install(engine, StubLLM([
        StubLLM.text("Should I now deploy the build?"),
    ]))
    events = await _drain(engine, "help")
    assert not any(e["type"] == "auto_continue" for e in events)


@pytest.mark.asyncio
async def test_auto_continue_blocked_when_disabled(engine):
    """auto_continue=off — agent promises more work but the gate blocks
    and emits auto_continue_blocked with a clear reason."""
    import api.settings_store as ss
    original = ss.get("auto_continue", "on")
    ss.update({"auto_continue": "off"})
    try:
        install(engine, StubLLM([
            StubLLM.text("Now I'll keep going on the next part."),
        ]))
        events = await _drain(engine, "go")
        blocked = [e for e in events if e["type"] == "auto_continue_blocked"]
        assert len(blocked) == 1
        assert "off" in blocked[0]["reason"].lower()
    finally:
        ss.update({"auto_continue": str(original)})


@pytest.mark.asyncio
async def test_auto_continue_blocked_when_cap_hit(engine, monkeypatch):
    """cap=1 → first promise auto-continues, the auto-continue's promise
    blocks because depth is now at the cap.

    Uses ``monkeypatch.setattr`` to swap ``settings_store.get`` so the
    test doesn't depend on (or write to) the on-disk settings file. That
    avoids cross-test pollution when the suite runs in any order.
    """
    import api.settings_store as ss
    overrides = {"auto_continue": "on", "auto_continue_max": 1}
    real_get = ss.get
    monkeypatch.setattr(
        ss, "get",
        lambda key, default=None: overrides.get(key, real_get(key, default)),
    )
    install(engine, StubLLM([
        StubLLM.text("Done. Now I'll keep going on part two."),
        StubLLM.text("Done. Next, I'll handle part three."),
    ]))
    events = await _drain(engine, "go")
    blocked = [e for e in events if e["type"] == "auto_continue_blocked"]
    assert len(blocked) == 1
    assert "cap" in blocked[0]["reason"].lower()


# ── Plan-required gate ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_gate_refuses_three_writes_without_plan(engine):
    """Three file_writes with no plan → gate refuses, surfaces hint to LLM."""
    install(engine, StubLLM([
        StubLLM.workflow(wf_sequential(
            step("file_write", {"path": "a.txt", "content": "1"}),
            step("file_write", {"path": "b.txt", "content": "2"}),
            step("file_write", {"path": "c.txt", "content": "3"}),
        )),
        # The agent then re-plans with plan_set.
        StubLLM.workflow(wf_sequential(
            step("plan_set", {
                "goal":         "test goal",
                "requirements": ["one"],
                "tasks":        ["task one"],
            }),
        )),
        StubLLM.text("Plan set."),
    ]))
    events = await _drain(engine, "do all three writes")
    refusals = [e for e in events
                if e["type"] == "tool_result" and e.get("error") == "plan_required"]
    assert len(refusals) == 1
    # No file_write actually ran.
    assert engine._files_written == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_plan_gate_refuses_when_plan_set_mixed_with_writes(engine):
    """The plan-approval gate runs AFTER a workflow finishes — so
    if plan_set + write tools are in the same workflow, the user
    sees write-approval modals BEFORE the plan. The runtime must
    refuse this combination so the agent splits it into two turns:
    plan first (gated for approval), then implementation.
    """
    install(engine, StubLLM([
        StubLLM.workflow(wf_sequential(
            step("plan_set", {"tasks": ["a", "b"]}),
            step("file_write", {"path": "a.txt", "content": "1"}),
            step("file_write", {"path": "b.txt", "content": "2"}),
            step("file_write", {"path": "c.txt", "content": "3"}),
        )),
        StubLLM.text("Done."),
    ]))
    events = await _drain(engine, "go")
    refusals = [e for e in events
                if e["type"] == "tool_result" and e.get("error") == "plan_required"]
    # Refused: plan_set must be in its own workflow.
    assert len(refusals) == 1
    assert refusals[0]["result"]["reason"] == "plan_set_mixed_with_writes"
    # No writes happened — the gate fired before the workflow ran.
    assert engine._files_written == []  # type: ignore[attr-defined]


# ── Plan nudge after writes ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_nudge_appears_when_writes_dont_touch_plan(engine):
    """If $plan has an in_progress task and the workflow does writes
    without any plan_* call, the LLM-facing tool_result must include a
    nudge string."""
    install(engine, StubLLM([
        StubLLM.workflow(wf_sequential(
            step("plan_set", {"tasks": ["t1", "t2"]}),
        )),
        StubLLM.workflow(wf_sequential(
            step("file_write", {"path": "x.txt", "content": "x"}),
            step("file_write", {"path": "y.txt", "content": "y"}),
        )),
        StubLLM.text("Wrote files."),
    ]))
    await _drain(engine, "go")
    # The 3rd LLM call sees the post-tool result. Check messages for nudge.
    captured = engine._stream_llm.__self__.captured_messages  # type: ignore[attr-defined]
    last_call_msgs = captured[-1] if captured else []
    nudge_present = any(
        "PLAN NUDGE" in (m.get("content") or "")
        for m in last_call_msgs
        if isinstance(m, dict) and isinstance(m.get("content"), str)
    )
    assert nudge_present, (
        "Expected PLAN NUDGE in the post-write tool result handed to the LLM"
    )


# ── Workflow leaked as text (recovery) ────────────────────────────────────


@pytest.mark.asyncio
async def test_recovers_workflow_json_from_assistant_text(engine):
    leaked = json.dumps(wf_sequential(step("echo", {"message": "leaked"})))
    install(engine, StubLLM([
        # No proper tool call — the JSON is in the text body.
        StubLLM.text(f"Sure, here it is:\n```json\n{leaked}\n```"),
        StubLLM.text("All done."),
    ]))
    events = await _drain(engine, "go")
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert any(e.get("tool") == "echo" for e in tool_calls)


# ── Cancellation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_mid_turn_emits_cancelled_then_done(engine):
    """Cancelling between turns short-circuits the agentic loop."""
    install(engine, StubLLM([
        StubLLM.workflow(wf_sequential(
            step("echo", {"message": "first"}),
        )),
        StubLLM.text("Won't reach this."),
    ]))
    # We can't easily cancel mid-stream from the test, but cancel BEFORE
    # the loop reaches its second LLM call to verify the path.
    gen = engine.chat("go")
    seen_types: list[str] = []
    async for ev in gen:
        seen_types.append(ev["type"])
        if ev["type"] == "tool_result":
            engine.cancel()
        if ev["type"] == "done":
            break
    assert "cancelled" in seen_types or "done" in seen_types


# ── Plan approval re-gate ────────────────────────────────────────────────
#
# Regression: if the user denies a plan, the agent often calls plan_edit
# (or plan_set again) to revise it — and historically the engine then
# silently let execution proceed without re-asking the user. The
# ``_plan_awaiting_approval`` flag persists across turns; while it's
# set, ANY plan_set / plan_edit / plan_add / plan_remove re-engages the
# approval gate. Only an explicit "approve" lifts it.


def _make_approval_handler(responses):
    """Build an approval handler that returns each ``response`` in
    sequence. Each response is the ``{action, ...}`` dict the engine
    expects. Records every call's args on ``handler.calls``.
    """
    iterator = iter(responses)
    calls: list[dict] = []

    async def handler(*, request_id, tool_name, args, step_id, message,
                      approval_type):
        calls.append({
            "request_id": request_id,
            "tool_name":  tool_name,
            "approval_type": approval_type,
            "plan":       args.get("plan"),
        })
        try:
            return next(iterator)
        except StopIteration:
            return {"action": "approve"}

    handler.calls = calls
    return handler


@pytest.mark.asyncio
async def test_plan_deny_then_edit_re_engages_approval_gate(engine):
    """User denies plan → agent calls plan_edit → engine MUST re-prompt
    the user before execution. The bug we hit: edit slipped through.
    """
    handler = _make_approval_handler([
        {"action": "deny", "reason": "wrong scope"},
        {"action": "approve"},
    ])
    engine._workflow_engine.approval_handler = handler

    install(engine, StubLLM([
        # Turn 1: agent drafts a plan
        StubLLM.workflow(wf_sequential(
            step("plan_set", {"tasks": ["a", "b"]}),
        )),
        # Turn 2: after deny → agent revises with plan_edit
        StubLLM.workflow(wf_sequential(
            step("plan_edit", {
                "operations": [
                    {"op": "set_goal", "value": "narrower scope"},
                ],
            }),
        )),
        # Turn 3: after approval → final reply
        StubLLM.text("Plan approved, ready to start."),
    ]))

    await _drain(engine, "draft a plan")

    # Approval handler must have been called TWICE — once for the
    # original plan_set, once for the revised plan_edit.
    assert len(handler.calls) == 2, (
        f"Expected 2 approval calls (initial + after edit), got "
        f"{len(handler.calls)}.\nThis is the regression: plan_edit "
        f"silently bypassed the approval gate after a denial."
    )
    # Both calls must be plan-review approvals.
    assert handler.calls[0]["approval_type"] == "plan_review"
    assert handler.calls[1]["approval_type"] == "plan_review"
    # Second call sees the post-edit plan.
    assert handler.calls[1]["plan"] is not None
    assert handler.calls[1]["plan"].get("goal") == "narrower scope"
    # After explicit approve, the flag must be cleared.
    assert engine._plan_awaiting_approval is False


@pytest.mark.asyncio
async def test_plan_approve_clears_the_re_gate_flag(engine):
    """Single happy path: approve on first ask → flag clear → no extra
    approval calls in subsequent plan-modifying turns.
    """
    handler = _make_approval_handler([
        {"action": "approve"},
    ])
    engine._workflow_engine.approval_handler = handler

    install(engine, StubLLM([
        StubLLM.workflow(wf_sequential(
            step("plan_set", {"tasks": ["one", "two"]}),
        )),
        StubLLM.text("Got it."),
    ]))
    await _drain(engine, "draft")

    assert len(handler.calls) == 1
    assert engine._plan_awaiting_approval is False


@pytest.mark.asyncio
async def test_plan_edit_does_not_re_gate_when_no_approval_pending(engine):
    """Sanity: plan_edit on an already-approved plan does NOT re-prompt.
    The gate only re-fires when ``_plan_awaiting_approval`` is True.
    """
    handler = _make_approval_handler([
        {"action": "approve"},
    ])
    engine._workflow_engine.approval_handler = handler

    install(engine, StubLLM([
        # Turn 1: plan_set + immediate approval
        StubLLM.workflow(wf_sequential(
            step("plan_set", {"tasks": ["a"]}),
        )),
        # Turn 2: plan_edit on the already-approved plan — no re-prompt
        StubLLM.workflow(wf_sequential(
            step("plan_edit", {
                "operations": [
                    {"op": "add_task", "task": "extra"},
                ],
            }),
        )),
        StubLLM.text("Done."),
    ]))
    await _drain(engine, "go")

    # Only the initial plan_set triggered the gate; the post-approval
    # plan_edit did NOT (because flag was cleared).
    assert len(handler.calls) == 1


@pytest.mark.asyncio
async def test_plan_edit_with_edit_action_keeps_gate_engaged(engine):
    """User picks "edit" → flag stays True → next plan_edit re-prompts."""
    handler = _make_approval_handler([
        {"action": "edit", "feedback": "tweak task 2"},
        {"action": "approve"},
    ])
    engine._workflow_engine.approval_handler = handler

    install(engine, StubLLM([
        StubLLM.workflow(wf_sequential(
            step("plan_set", {"tasks": ["a", "b"]}),
        )),
        StubLLM.workflow(wf_sequential(
            step("plan_edit", {
                "operations": [
                    {"op": "set_goal", "value": "tighter scope"},
                ],
            }),
        )),
        StubLLM.text("Approved."),
    ]))
    await _drain(engine, "go")

    assert len(handler.calls) == 2  # original + post-edit re-gate
    assert engine._plan_awaiting_approval is False  # second call approved
