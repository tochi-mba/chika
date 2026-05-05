"""Plan-required gate: multi-step write workflows MUST have an active
plan (or include a plan_* tool in the workflow itself).

Without this enforcement the agent skipped planning even after loading
the SKILL.md — exactly the failure mode the user reported. The gate
makes the requirement a runtime invariant, not a prompt suggestion.
"""
from __future__ import annotations

import asyncio
import time

from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VarType, VariableStore
from chika.core.workflow_engine import WorkflowEngine


def _build_engine():
    """Engine with all the WRITE_TOOLS the gate cares about registered as
    no-ops, plus plan_set as a real tool that puts a plan into $vars."""
    reg = ToolRegistry()

    async def _noop(**_kw):
        return {"ok": True}

    for name in ("file_write", "shell_exec", "python_run", "live_server",
                 "scaffold_web_app", "git_commit"):
        reg.register(ToolDefinition(
            name=name, description="x",
            parameters={"type": "object", "properties": {}}, handler=_noop,
        ))

    return WorkflowEngine(reg, VariableStore())


def _drain(eng: WorkflowEngine, workflow: dict) -> list[dict]:
    async def _go():
        return [ev async for ev in eng.execute(workflow)]
    return asyncio.run(_go())


# ── Refuse-and-retry on a 3+ write workflow without a plan ───────────────

def test_three_write_workflow_without_plan_is_refused():
    eng = _build_engine()
    wf = {
        "type":  "sequential", "id": "wf",
        "steps": [
            {"tool": "file_write",  "id": "s1", "args": {}},
            {"tool": "shell_exec",  "id": "s2", "args": {}},
            {"tool": "live_server", "id": "s3", "args": {}},
        ],
    }
    events = _drain(eng, wf)
    types = [e.get("type") for e in events]
    # Gate fires synthetic plan_gate tool_call + tool_result.
    assert "tool_call" in types
    plan_gate_call = [e for e in events
                      if e.get("type") == "tool_call" and e.get("tool") == "plan_gate"]
    assert len(plan_gate_call) == 1
    assert plan_gate_call[0]["args"].get("_auto") is True

    refusal = [e for e in events
               if e.get("type") == "tool_result"
               and e.get("error") == "plan_required"]
    assert len(refusal) == 1
    payload = refusal[0]["result"]
    assert payload["write_count"] == 3
    assert "file_write" in payload["writes_used"]
    assert "Generate a new workflow" not in payload.get("hint", "")  # phrasing
    assert "plan_set" in payload["hint"]

    # Workflow body never ran.
    assert "workflow_start" not in types
    assert all(e.get("type") != "tool_call"
               or e.get("tool") in ("plan_gate",)
               for e in events)


def test_two_write_workflow_is_NOT_refused():
    """Below the threshold — single-or-double-write jobs are exempt; the
    soft prompt rule still nudges if planning is wanted."""
    eng = _build_engine()
    wf = {
        "type":  "sequential", "id": "wf",
        "steps": [
            {"tool": "file_write", "id": "s1", "args": {}},
            {"tool": "shell_exec", "id": "s2", "args": {}},
        ],
    }
    events = _drain(eng, wf)
    types = [e.get("type") for e in events]
    assert "workflow_start" in types
    plan_refusal = [e for e in events
                    if e.get("type") == "tool_result"
                    and e.get("error") == "plan_required"]
    assert plan_refusal == []


def test_workflow_with_plan_set_step_is_NOT_refused():
    """The agent can break out of the gate by including plan_set in the
    SAME workflow as the first step."""
    eng = _build_engine()
    # Register plan_set as a noop tool for this test.
    eng._tools.register(ToolDefinition(
        name="plan_set", description="x",
        parameters={"type": "object", "properties": {}},
        handler=lambda **_kw: asyncio.sleep(0, result={"ok": True})
    ))

    async def _async_noop(**_kw):
        return {"ok": True}
    eng._tools.register(ToolDefinition(
        name="plan_set", description="x",
        parameters={"type": "object", "properties": {}},
        handler=_async_noop,
    ))

    wf = {
        "type":  "sequential", "id": "wf",
        "steps": [
            {"tool": "plan_set",   "id": "s0", "args": {"tasks": ["a"]}},
            {"tool": "file_write", "id": "s1", "args": {}},
            {"tool": "shell_exec", "id": "s2", "args": {}},
            {"tool": "live_server","id": "s3", "args": {}},
        ],
    }
    events = _drain(eng, wf)
    types = [e.get("type") for e in events]
    assert "workflow_start" in types
    plan_refusal = [e for e in events
                    if e.get("type") == "tool_result"
                    and e.get("error") == "plan_required"]
    assert plan_refusal == []


def test_workflow_with_existing_plan_is_NOT_refused():
    """If $plan already exists with at least one task, the gate stays out
    of the way — the agent has already planned in a prior turn."""
    eng = _build_engine()
    eng._vars.set("plan", {
        "tasks": [{"id": "t1", "text": "x", "status": "in_progress"}],
        "created_at": time.time(),
        "updated_at": time.time(),
    }, VarType.JSON, source="plan:set")

    wf = {
        "type":  "sequential", "id": "wf",
        "steps": [
            {"tool": "file_write",  "id": "s1", "args": {}},
            {"tool": "shell_exec",  "id": "s2", "args": {}},
            {"tool": "live_server", "id": "s3", "args": {}},
            {"tool": "git_commit",  "id": "s4", "args": {}},
        ],
    }
    events = _drain(eng, wf)
    plan_refusal = [e for e in events
                    if e.get("type") == "tool_result"
                    and e.get("error") == "plan_required"]
    assert plan_refusal == [], (
        "existing plan should suppress the gate"
    )


def test_scaffold_web_app_alone_requires_plan():
    """Single ``scaffold_web_app`` (write_count=1) should still trigger
    the gate because project creation always demands a plan, regardless
    of write count. The previous threshold-only gate let "scaffold + a
    couple edits" workflows skip planning, which the user reported."""
    reg = ToolRegistry()

    async def _noop(**_kw):
        return {"ok": True}

    reg.register(ToolDefinition(
        name="scaffold_web_app", description="x",
        parameters={"type": "object", "properties": {}}, handler=_noop,
    ))
    eng = WorkflowEngine(reg, VariableStore())

    wf = {
        "type":  "sequential", "id": "wf",
        "steps": [
            {"tool": "scaffold_web_app", "id": "s1",
             "args": {"stack": "vanilla", "name": "demo"}},
        ],
    }
    events = _drain(eng, wf)
    refusal = [e for e in events
               if e.get("type") == "tool_result"
               and e.get("error") == "plan_required"]
    assert len(refusal) == 1
    payload = refusal[0]["result"]
    assert "scaffold_web_app" in payload["creation_tools"]
    assert "scaffold_web_app" in payload["hint"]
    # Workflow body never ran.
    assert all(e.get("type") != "tool_call" or e.get("tool") in ("plan_gate",)
               for e in events)


def test_scaffold_web_app_with_plan_is_NOT_refused():
    """Active plan in $vars exempts scaffold_web_app from the gate."""
    import time as _t

    from chika.core.variable_store import VarType
    reg = ToolRegistry()

    async def _noop(**_kw):
        return {"ok": True}

    reg.register(ToolDefinition(
        name="scaffold_web_app", description="x",
        parameters={"type": "object", "properties": {}}, handler=_noop,
    ))
    eng = WorkflowEngine(reg, VariableStore())
    eng._vars.set("plan", {
        "tasks": [{"id": "t1", "text": "scaffold", "status": "in_progress"}],
        "created_at": _t.time(),
        "updated_at": _t.time(),
    }, VarType.JSON, source="plan:set")

    wf = {
        "type":  "sequential", "id": "wf",
        "steps": [{"tool": "scaffold_web_app", "id": "s1",
                   "args": {"stack": "vanilla", "name": "demo"}}],
    }
    events = _drain(eng, wf)
    refusal = [e for e in events
               if e.get("type") == "tool_result"
               and e.get("error") == "plan_required"]
    assert refusal == []


def test_read_only_workflow_is_NOT_refused():
    """A workflow that only reads (no write-class tools at all) must
    never trip the gate, no matter how many steps."""
    reg = ToolRegistry()

    async def _noop(**_kw):
        return {"ok": True}

    for name in ("file_read", "git_status", "git_diff", "git_log"):
        reg.register(ToolDefinition(
            name=name, description="x",
            parameters={"type": "object", "properties": {}}, handler=_noop,
        ))
    eng = WorkflowEngine(reg, VariableStore())

    wf = {
        "type":  "sequential", "id": "wf",
        "steps": [
            {"tool": "file_read",  "id": "s1", "args": {}},
            {"tool": "git_status", "id": "s2", "args": {}},
            {"tool": "git_diff",   "id": "s3", "args": {}},
            {"tool": "git_log",    "id": "s4", "args": {}},
        ],
    }
    events = _drain(eng, wf)
    plan_refusal = [e for e in events
                    if e.get("type") == "tool_result"
                    and e.get("error") == "plan_required"]
    assert plan_refusal == []
    assert "workflow_start" in [e.get("type") for e in events]
