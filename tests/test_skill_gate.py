"""Skill-gate: a skill's tools cannot fire until its SKILL.md is loaded.

The runtime invariant: when the agent calls a tool that belongs to a skill
whose SKILL.md hasn't been read yet, the workflow engine auto-runs
``skill_load`` first and streams the events. This makes "always read
SKILL.md before using a skill's tools" enforceable, not just a prompt
suggestion.
"""
from __future__ import annotations

import asyncio

from chika.core.skill_registry import Skill, SkillRegistry
from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore
from chika.core.workflow_engine import WorkflowEngine


def _build():
    """Engine wired with one fake skill (with one tool) plus skill_load."""
    tools = ToolRegistry()
    vs = VariableStore()

    async def _fake_skill_tool(**_kw):
        return {"ok": True, "from": "fake_skill_tool"}

    async def _fake_skill_load(skill: str, **_kw):
        return {
            "ok":         True,
            "skill":      skill,
            "doc":        f"# {skill} skill\n(auto-loaded)",
            "char_count": 120,
            "condensed":  False,
        }

    tools.register(ToolDefinition(
        name="fake_tool",
        description="Tool belonging to the fake skill",
        parameters={"type": "object", "properties": {}},
        handler=_fake_skill_tool,
    ))
    tools.register(ToolDefinition(
        name="skill_load",
        description="Load a SKILL.md",
        parameters={
            "type": "object",
            "properties": {"skill": {"type": "string"}},
            "required": ["skill"],
        },
        handler=_fake_skill_load,
    ))

    eng = WorkflowEngine(tools, vs)

    # Pretend "fake" skill owns "fake_tool". We don't actually need a
    # PromptBuilder/MemoryManager for this test — we just need the registry
    # internal map to look the way SkillRegistry produces.
    sr = type("StubReg", (), {})()
    sr._skills = {
        "fake": Skill(
            name="fake", description="testing",
            tools=[tools.get("fake_tool")],
        ),
    }
    eng.set_skill_registry(sr)
    return eng


def _drain(workflow: dict) -> list[dict]:
    eng = _build()
    async def _run():
        return [ev async for ev in eng.execute(workflow)]
    return asyncio.run(_run())


def _drain_with_engine(eng: WorkflowEngine, workflow: dict) -> list[dict]:
    async def _run():
        return [ev async for ev in eng.execute(workflow)]
    return asyncio.run(_run())


# ── Refuse-and-retry: first call doesn't run, second one does ─────────────

def test_first_skill_tool_call_is_refused_with_doc():
    """A first-time skill tool call must be REFUSED — the SKILL.md is
    surfaced to the agent and the original tool does NOT run. The agent
    re-plans on the next turn with the doc in context."""
    workflow = {
        "type":  "sequential",
        "id":    "wf",
        "steps": [{"tool": "fake_tool", "id": "s1", "args": {}}],
    }
    events = _drain(workflow)
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    results = [e for e in events if e.get("type") == "tool_result"]

    # Order: skill_load (auto, succeeds) → fake_tool (REFUSED, didn't run).
    assert [c["tool"] for c in tool_calls] == ["skill_load", "fake_tool"]
    assert [r["tool"] for r in results] == ["skill_load", "fake_tool"]

    # The auto-load is flagged so the UI can label it.
    assert tool_calls[0]["args"].get("_auto") is True

    # skill_load succeeded.
    assert results[0].get("error") is None

    # The original tool's result is the skill_doc_required refusal.
    refusal = results[1]
    assert refusal["error"] == "skill_doc_required"
    assert isinstance(refusal["result"], dict)
    assert refusal["result"].get("skill") == "fake"
    assert refusal["result"].get("tool_blocked") == "fake_tool"
    # The doc body MUST be embedded so the LLM can use it on retry.
    assert "(auto-loaded)" in (refusal["result"].get("doc") or "")
    # Hint tells the agent to re-plan.
    assert "Generate a new" in refusal["result"].get("hint", "")

    # Bookkeeping: the tool's actual handler (which would have set
    # `from: fake_skill_tool` in the result) DID NOT RUN.
    assert "from" not in (refusal["result"] or {})


def test_second_skill_tool_call_runs_normally():
    """After the first refusal the skill is loaded — subsequent calls
    pass through and the tool actually runs."""
    eng = _build()
    # First workflow — refused.
    eng_run1 = _drain_with_engine(eng, {
        "type": "sequential", "id": "wf1",
        "steps": [{"tool": "fake_tool", "id": "s1", "args": {}}],
    })
    refused = [e for e in eng_run1
               if e.get("type") == "tool_result" and e.get("tool") == "fake_tool"]
    assert refused[0]["error"] == "skill_doc_required"

    # Second workflow — passes through, real handler runs.
    eng_run2 = _drain_with_engine(eng, {
        "type": "sequential", "id": "wf2",
        "steps": [{"tool": "fake_tool", "id": "s2", "args": {}}],
    })
    tool_calls = [e["tool"] for e in eng_run2 if e.get("type") == "tool_call"]
    # No skill_load auto-fire on the second run.
    assert tool_calls == ["fake_tool"]
    # The real handler's payload arrived this time.
    real_results = [e for e in eng_run2
                    if e.get("type") == "tool_result" and e.get("tool") == "fake_tool"]
    assert real_results[0].get("error") is None
    assert real_results[0]["result"].get("from") == "fake_skill_tool"


def test_refusal_aborts_the_sequential():
    """Refused calls produce an error tool_result, which must abort the
    sequential — subsequent steps in the same workflow do NOT run."""
    eng = _build()
    workflow = {
        "type": "sequential", "id": "wf",
        "steps": [
            {"tool": "fake_tool", "id": "s1", "args": {}},
            {"tool": "fake_tool", "id": "s2", "args": {}},
        ],
    }
    events = _drain_with_engine(eng, workflow)
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    # Sequence: skill_load → fake_tool (refused). Step 2 NEVER runs because
    # the sequential aborts on the first error.
    assert [c["tool"] for c in tool_calls] == ["skill_load", "fake_tool"]


def test_explicit_skill_load_marks_skill_as_loaded():
    """If the agent calls skill_load itself, the gate must NOT redundantly
    re-fire skill_load before the next skill tool."""
    eng = _build()
    workflow = {
        "type":  "sequential",
        "id":    "wf",
        "steps": [
            {"tool": "skill_load", "id": "s0", "args": {"skill": "fake"}},
            {"tool": "fake_tool",  "id": "s1", "args": {}},
        ],
    }
    events = _drain_with_engine(eng, workflow)
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    # Exactly two calls — the explicit skill_load and the fake_tool.
    # No auto-injected duplicate.
    assert len(tool_calls) == 2, f"unexpected tool calls: {tool_calls}"
    assert [c["tool"] for c in tool_calls] == ["skill_load", "fake_tool"]
    assert tool_calls[0]["args"].get("_auto") is not True


def test_skill_load_itself_is_not_gated():
    """skill_load is on the gate's exempt list — calling it can't infinite-loop."""
    eng = _build()
    workflow = {
        "type":  "sequential",
        "id":    "wf",
        "steps": [{"tool": "skill_load", "id": "s0", "args": {"skill": "fake"}}],
    }
    events = _drain_with_engine(eng, workflow)
    # Exactly one tool_call (the explicit one) — no recursion.
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    assert len(tool_calls) == 1


def test_non_skill_tools_are_not_gated():
    """Tools that don't belong to any skill (file_read etc.) must not trigger
    spurious skill_load calls."""
    tools = ToolRegistry()

    async def _free(**_kw):
        return {"ok": True}

    tools.register(ToolDefinition(
        name="standalone_tool",
        description="Not part of any skill",
        parameters={"type": "object", "properties": {}},
        handler=_free,
    ))
    eng = WorkflowEngine(tools, VariableStore())
    # No skill registry wired → empty _tool_to_skill index → gate is no-op
    workflow = {
        "type":  "sequential",
        "id":    "wf",
        "steps": [{"tool": "standalone_tool", "id": "s1", "args": {}}],
    }
    events = asyncio.run(_drain_collect(eng, workflow))
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    assert len(tool_calls) == 1, (
        f"non-skill tool should not trigger skill_load, got {tool_calls}"
    )


async def _drain_collect(eng, workflow):
    return [ev async for ev in eng.execute(workflow)]


# ── Defensive: missing skill_load tool means gate degrades gracefully ──

def test_gate_no_ops_if_skill_load_tool_missing():
    """Old engines without skill_load registered shouldn't crash — the gate
    silently marks the skill loaded and the tool runs."""
    tools = ToolRegistry()

    async def _fake(**_kw):
        return {"ok": True}

    tools.register(ToolDefinition(
        name="fake_tool",
        description="Tool with no skill_load available",
        parameters={"type": "object", "properties": {}},
        handler=_fake,
    ))
    eng = WorkflowEngine(tools, VariableStore())
    sr = type("StubReg", (), {})()
    sr._skills = {
        "fake": Skill(name="fake", description="x",
                      tools=[tools.get("fake_tool")]),
    }
    eng.set_skill_registry(sr)
    workflow = {
        "type":  "sequential",
        "id":    "wf",
        "steps": [{"tool": "fake_tool", "id": "s1", "args": {}}],
    }
    events = asyncio.run(_drain_collect(eng, workflow))
    tool_calls = [e for e in events if e.get("type") == "tool_call"]
    # Only fake_tool ran — skill_load not registered → gate is no-op,
    # tool dispatches normally.
    assert [c["tool"] for c in tool_calls] == ["fake_tool"]
    results = [e for e in events if e.get("type") == "tool_result"]
    assert results[0].get("error") is None


def test_gate_passes_through_when_skill_load_returns_error():
    """If skill_load fails (e.g. SKILL.md missing on disk), the gate must
    NOT lock the user out of the tool — it degrades to pass-through."""
    tools = ToolRegistry()

    async def _fake_tool(**_kw):
        return {"ok": True, "from": "real_handler"}

    async def _failing_skill_load(skill: str, **_kw):
        return {"error": "no_doc", "skill": skill}

    tools.register(ToolDefinition(
        name="fake_tool", description="x",
        parameters={"type": "object", "properties": {}}, handler=_fake_tool,
    ))
    tools.register(ToolDefinition(
        name="skill_load", description="x",
        parameters={"type": "object",
                    "properties": {"skill": {"type": "string"}}},
        handler=_failing_skill_load,
    ))

    eng = WorkflowEngine(tools, VariableStore())
    sr = type("StubReg", (), {})()
    sr._skills = {
        "fake": Skill(name="fake", description="x",
                      tools=[tools.get("fake_tool")]),
    }
    eng.set_skill_registry(sr)

    events = asyncio.run(_drain_collect(eng, {
        "type": "sequential", "id": "wf",
        "steps": [{"tool": "fake_tool", "id": "s1", "args": {}}],
    }))
    results = [e for e in events
               if e.get("type") == "tool_result" and e.get("tool") == "fake_tool"]
    # The real handler ran — gate degraded to pass-through.
    assert len(results) == 1
    assert results[0].get("error") is None
    assert results[0]["result"].get("from") == "real_handler"

