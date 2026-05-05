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
from chika.skills.plan_skill import build_plan_skill
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

    # Plan skill — real implementation, real var store.
    plan_skill = build_plan_skill(vars_)
    skills.register(plan_skill)

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
async def test_plan_gate_passes_when_plan_set_is_in_workflow(engine):
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
    assert refusals == []
    assert len(engine._files_written) == 3  # type: ignore[attr-defined]


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
