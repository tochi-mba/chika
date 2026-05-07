"""Plan-tool kwarg alias resolution.

LLMs often call ``plan_set(steps=[...])`` instead of ``plan_set(tasks=[...])``,
or ``plan_update(id=, state=)`` instead of ``plan_update(task_id=, status=)``.
The plan tools absorb a fixed set of aliases so the agent doesn't crash
mid-turn on a "missing required argument" error.

Used to live in ``tests/test_skill_gate.py`` — moved here so the test
sits next to the code it exercises (skill-isolation contract).
"""
from __future__ import annotations

import asyncio

import pytest

from chika.core.variable_store import VariableStore
from chika.skills.plan_skill import _make_plan_tools


def test_plan_set_accepts_spurious_kwargs():
    vs = VariableStore()
    plan_set, *_ = _make_plan_tools(vs)
    out = asyncio.run(plan_set(tasks=["one", "two"], name="my plan",
                               id="p1", title="x"))
    assert "error" not in out, f"plan_set must absorb extra kwargs, got {out}"
    assert out["count"] == 2


@pytest.mark.parametrize("alias", ["steps", "items", "list", "plan", "todos"])
def test_plan_set_accepts_alias_for_tasks_kwarg(alias):
    vs = VariableStore()
    plan_set, *_ = _make_plan_tools(vs)
    out = asyncio.run(plan_set(**{alias: ["a", "b", "c"]}))
    assert "error" not in out, f"alias {alias!r} should resolve, got {out}"
    assert out["count"] == 3


def test_plan_set_with_no_tasks_returns_clear_error():
    plan_set, *_ = _make_plan_tools(VariableStore())
    out = asyncio.run(plan_set(name="empty-plan", id="x"))
    assert "error" in out
    assert "aliases" in out["error"].lower() or "tasks" in out["error"].lower()


@pytest.mark.parametrize("alias_id, alias_status", [
    ("id",     "state"),
    ("task",   "new_status"),
    ("taskId", "state"),
])
def test_plan_update_accepts_aliases(alias_id, alias_status):
    vs = VariableStore()
    plan_set, plan_update, *_ = _make_plan_tools(vs)
    asyncio.run(plan_set(tasks=["a", "b"]))
    out = asyncio.run(plan_update(**{alias_id: "t1", alias_status: "done"}))
    assert "error" not in out
    tasks = out["plan"]["tasks"]
    assert tasks[0]["status"] == "done"


@pytest.mark.parametrize("alias", ["steps", "items", "list", "todos"])
def test_plan_add_accepts_alias_for_tasks(alias):
    vs = VariableStore()
    plan_set, _, _, plan_add, _, *_extra = _make_plan_tools(vs)
    asyncio.run(plan_set(tasks=["seed"]))
    out = asyncio.run(plan_add(**{alias: ["new1", "new2"]}))
    assert "error" not in out
    assert len(out["plan"]["tasks"]) == 3


@pytest.mark.parametrize("alias", ["ids", "id", "task_id"])
def test_plan_remove_accepts_alias(alias):
    vs = VariableStore()
    plan_set, _, _, _, plan_remove, *_extra = _make_plan_tools(vs)
    asyncio.run(plan_set(tasks=["a", "b", "c"]))
    out = asyncio.run(plan_remove(**{alias: "t1"}))
    assert "error" not in out
    assert out["removed"] == ["t1"]
