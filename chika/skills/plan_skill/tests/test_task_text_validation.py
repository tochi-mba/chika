"""``plan_set`` rejects tasks missing the ``text`` field.

The user reported a stall: after a ``plan_set`` call where the LLM
emitted tasks with ``id`` + ``status`` but no ``text``, the
approval modal showed a wall of empty ``[pending]`` markers — no
context to evaluate, the user couldn't make an informed choice.

The validator at the top of ``plan_set`` now refuses any plan with
empty-text tasks (or empty-text subtasks at any depth), returning a
structured error that names the offending IDs so the LLM retries
with proper descriptions.
"""
from __future__ import annotations

import asyncio

from chika.core.variable_store import VariableStore
from chika.skills.plan_skill import _make_plan_tools


def _setup():
    store = VariableStore()
    plan_set, *_ = _make_plan_tools(store)
    return plan_set


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_plan_set_rejects_top_level_task_with_empty_text():
    """A top-level task missing ``text`` triggers the validator."""
    plan_set = _setup()
    out = _run(plan_set(tasks=[
        {"id": "scaffold", "status": "pending"},   # no text
        {"id": "implement", "status": "pending", "text": "Build the engine"},
    ]))
    assert out.get("error") == "task_missing_text", out
    assert "scaffold" in out["tasks"]


def test_plan_set_rejects_subtask_with_empty_text():
    """A subtask missing text is caught — validator recurses."""
    plan_set = _setup()
    out = _run(plan_set(tasks=[
        {"id": "scaffold", "text": "Set up project", "status": "pending",
         "subtasks": [
             {"id": "scaffold.dir", "status": "pending"},  # no text
         ]},
    ]))
    assert out.get("error") == "task_missing_text", out
    # Path-style ID so the LLM knows exactly which one to fix.
    assert any("scaffold.dir" in p for p in out["tasks"])


def test_plan_set_rejects_whitespace_only_text():
    """``text=" "`` is treated the same as empty — strip + check."""
    plan_set = _setup()
    out = _run(plan_set(tasks=[{"id": "x", "text": "    "}]))
    assert out.get("error") == "task_missing_text"


def test_plan_set_accepts_string_form_tasks():
    """``tasks=['do this', 'do that']`` is the simple shape — every
    item has implicit text. Must NOT trip the validator."""
    plan_set = _setup()
    out = _run(plan_set(tasks=["do this", "do that"]))
    assert "error" not in out, out
    assert out["count"] == 2


def test_plan_set_accepts_dict_tasks_with_text():
    """The verbose-template shape works fine."""
    plan_set = _setup()
    out = _run(plan_set(tasks=[
        {"id": "t1", "text": "Set up scaffolding"},
        {"id": "t2", "text": "Wire the API",
         "subtasks": [
             {"id": "t2.1", "text": "Define routes"},
             {"id": "t2.2", "text": "Add auth"},
         ]},
    ]))
    assert "error" not in out, out
    assert out["count"] == 2


def test_plan_set_error_payload_includes_hint():
    """The error message must guide the LLM to fix the call —
    structured tasks list + a free-form hint."""
    plan_set = _setup()
    out = _run(plan_set(tasks=[{"id": "x", "status": "pending"}]))
    assert out["error"] == "task_missing_text"
    assert "tasks" in out
    assert isinstance(out["tasks"], list)
    assert "hint" in out
    assert "text" in out["hint"]


def test_plan_set_no_partial_writes_when_validation_fails():
    """Validation failure must NOT write a half-baked plan to the
    variable store. The user shouldn't end up with a malformed plan
    they then have to manually clear."""
    store = VariableStore()
    plan_set, *_ = _make_plan_tools(store)
    out = _run(plan_set(tasks=[{"id": "x", "status": "pending"}]))
    assert out["error"] == "task_missing_text"
    assert store.get("plan") is None, (
        "validation failure must not commit anything to the variable store"
    )


# ── Renderer behaviour at approval time (engine-side) ────────────────
#
# These exercise the engine's ``_request_plan_approval`` end-to-end
# via a stub approval handler that captures the rendered ``message``.
# The engine module is the source of truth for what the user sees in
# the approval modal — testing the format here guards against
# regressions like the "first task already in_progress" confusion that
# triggered this hardening.


import pytest

from chika.core.engine import ChikaEngine


def _make_engine_for_approval(monkeypatch):
    """Bare ChikaEngine wired with a captured-output approval handler."""
    from chika.core.memory_manager import MemoryManager
    from chika.core.prompt_builder import PromptBuilder
    from chika.core.skill_registry import SkillRegistry
    from chika.core.tool_registry import ToolRegistry
    from chika.core.variable_store import VariableStore

    # Avoid importing config / make_client during construction —
    # patch the bits the constructor reaches for so tests don't need
    # an LLM provider configured.
    monkeypatch.setattr("config.make_client", lambda: None)

    tools = ToolRegistry()
    vs = VariableStore()
    mem = MemoryManager(path=":memory:", max_tokens=1000)
    prompt = PromptBuilder()
    skills = SkillRegistry(tools, mem, prompt)
    return ChikaEngine(
        tool_registry=tools,
        variable_store=vs,
        memory_manager=mem,
        prompt_builder=prompt,
        skill_registry=skills,
    )


@pytest.mark.asyncio
async def test_approval_renderer_omits_status_labels(monkeypatch):
    """At approval time nothing has run yet, so showing
    ``[in_progress]`` next to a task makes the user think it's
    already executing. The renderer must show a clean numbered
    to-do list with no status markers."""
    eng = _make_engine_for_approval(monkeypatch)
    captured: dict = {}

    async def handler(*, request_id, tool_name, args, step_id,
                      message, approval_type):
        captured["message"] = message
        return {"action": "approve"}

    eng._workflow_engine.approval_handler = handler  # type: ignore[attr-defined]
    plan = {
        "goal": "Build a thing",
        "requirements": ["Must compile"],
        "tasks": [
            {"id": "t1", "status": "in_progress", "text": "Scaffold"},
            {"id": "t2", "status": "pending", "text": "Implement"},
            {"id": "t3", "status": "pending", "text": "Test"},
        ],
    }
    await eng._request_plan_approval(plan)
    msg = captured["message"]
    # No status labels anywhere — the auto-promoted "in_progress"
    # tag must not leak into the user-facing approval prompt.
    assert "[in_progress]" not in msg
    assert "[pending]" not in msg
    assert "[done]" not in msg
    # All three task texts present
    assert "Scaffold" in msg
    assert "Implement" in msg
    assert "Test" in msg
    # Numbered top-level (the user sees a clean ordered list)
    assert "1. Scaffold" in msg
    assert "2. Implement" in msg
    assert "3. Test" in msg


@pytest.mark.asyncio
async def test_approval_renderer_falls_back_to_id_for_empty_text(monkeypatch):
    """Defence in depth — if a plan with empty-text tasks ever
    reaches the renderer (e.g. via plan_edit), the user sees the
    task ID rather than a blank line."""
    eng = _make_engine_for_approval(monkeypatch)
    captured: dict = {}

    async def handler(*, request_id, tool_name, args, step_id,
                      message, approval_type):
        captured["message"] = message
        return {"action": "approve"}

    eng._workflow_engine.approval_handler = handler  # type: ignore[attr-defined]
    plan = {
        "goal": "Build a thing",
        "requirements": [],
        "tasks": [
            {"id": "scaffold", "status": "pending", "text": ""},
            {"id": "engine", "status": "pending", "text": "Wire engine"},
        ],
    }
    await eng._request_plan_approval(plan)
    msg = captured["message"]
    assert "<scaffold>" in msg
    assert "(missing description)" in msg
    assert "Wire engine" in msg
