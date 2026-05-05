"""Workflow size limits are SOFT — oversize workflows execute with a warning.

Prior behaviour: workflows over ``MAX_WORKFLOW_STEPS`` aborted with an
``error`` event and never ran. That blocked legitimate work whenever the
agent's planning was slightly off. New behaviour: emit a
``validation_warning`` and keep executing. Genuinely runaway workflows
(>10× the soft limit) still abort hard.
"""
from __future__ import annotations

import asyncio

import config
from chika.core.tool_registry import ToolDefinition, ToolRegistry
from chika.core.variable_store import VariableStore
from chika.core.workflow_engine import WorkflowEngine


def _build_engine():
    registry = ToolRegistry()

    async def _noop(**_kw):
        return {"ok": True}

    registry.register(ToolDefinition(
        name="noop",
        description="No-op tool used by tests.",
        parameters={"type": "object", "properties": {}},
        handler=_noop,
    ))
    return WorkflowEngine(registry, VariableStore())


def _drain(workflow: dict) -> list[dict]:
    eng = _build_engine()
    async def _run():
        return [ev async for ev in eng.execute(workflow)]
    return asyncio.run(_run())


def test_oversize_workflow_warns_but_executes():
    n = config.MAX_WORKFLOW_STEPS + 5  # comfortably over the soft limit
    workflow = {
        "type":  "sequential",
        "id":    "oversize",
        "steps": [{"tool": "noop", "id": f"s{i}", "args": {}} for i in range(n)],
    }
    events = _drain(workflow)
    types = [e.get("type") for e in events]

    # The runtime emitted exactly one oversize warning.
    warnings = [e for e in events if e.get("type") == "validation_warning"
                and e.get("reason") == "workflow_oversize"]
    assert len(warnings) == 1, f"expected 1 oversize warning, got {warnings!r}"

    # Crucially: NO 'error' event AND we still see workflow_done +
    # tool_result events for every step (i.e. execution actually ran).
    assert "error" not in types, f"oversize warning must not block execution: {types}"
    assert types.count("workflow_start") == 1
    assert types.count("workflow_done") == 1
    # Every step ran (one tool_call + tool_result per step)
    assert types.count("tool_call") == n
    assert types.count("tool_result") == n


def test_workflow_under_soft_limit_emits_no_warning():
    n = max(1, config.MAX_WORKFLOW_STEPS - 1)
    workflow = {
        "type":  "sequential",
        "id":    "under",
        "steps": [{"tool": "noop", "id": f"s{i}", "args": {}} for i in range(n)],
    }
    events = _drain(workflow)
    warnings = [e for e in events
                if e.get("type") == "validation_warning"
                and e.get("reason") in ("workflow_oversize",
                                        "workflow_oversize_writes")]
    assert warnings == [], f"unexpected warning under soft limit: {warnings!r}"


def test_runaway_workflow_still_aborts():
    """Genuinely huge workflows (>10× soft limit) hit the hard safety cap."""
    cap = max(config.MAX_WORKFLOW_STEPS * 10, 80)
    n = cap + 2
    workflow = {
        "type":  "sequential",
        "id":    "runaway",
        "steps": [{"tool": "noop", "id": f"s{i}", "args": {}} for i in range(n)],
    }
    events = _drain(workflow)
    types = [e.get("type") for e in events]
    assert "error" in types, "hard cap must abort with an error event"
    # Hard-cap aborts before ANY step runs.
    assert "tool_call" not in types
