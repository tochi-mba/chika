"""Tests for the plan skill — session-scoped task tracking."""
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio

from chika.core.variable_store import VariableStore
from chika.skills.plan_skill import _make_plan_tools, build_plan_skill


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _tools():
    store = VariableStore()
    plan_set, plan_update, plan_get = _make_plan_tools(store)
    return store, plan_set, plan_update, plan_get


def test_plan_set_creates_list_and_marks_first_in_progress():
    store, plan_set, _, plan_get = _tools()
    result = _run(plan_set(["read config", "patch the bug", "run tests"]))
    assert result["count"] == 3
    plan = result["plan"]
    assert plan["tasks"][0]["status"] == "in_progress"  # first pending auto-promoted
    assert plan["tasks"][1]["status"] == "pending"
    assert plan["tasks"][2]["status"] == "pending"
    assert plan["tasks"][0]["id"] == "t1"
    # Stored in the variable store too
    assert store.get("plan") is not None


def test_plan_set_rejects_empty():
    _, plan_set, _, _ = _tools()
    assert _run(plan_set([]))["error"]
    assert _run(plan_set(None))["error"]


def test_plan_set_accepts_mixed_types():
    """Tasks can be strings OR {id, text, status} objects."""
    _, plan_set, _, _ = _tools()
    r = _run(plan_set([
        "first task",
        {"id": "custom", "text": "second", "status": "pending"},
        {"text": "third (auto-id)"},
    ]))
    tasks = r["plan"]["tasks"]
    assert tasks[0]["id"] == "t1"
    assert tasks[0]["text"] == "first task"
    assert tasks[1]["id"] == "custom"
    assert tasks[2]["id"] == "t3"


def test_plan_update_marks_done_and_auto_promotes_next():
    store, plan_set, plan_update, _ = _tools()
    _run(plan_set(["A", "B", "C"]))
    # t1 is in_progress, t2 and t3 are pending
    r = _run(plan_update("t1", "done"))
    tasks = r["plan"]["tasks"]
    assert tasks[0]["status"] == "done"
    # Next pending auto-promotes to in_progress
    assert tasks[1]["status"] == "in_progress"
    assert tasks[2]["status"] == "pending"


def test_plan_update_can_rewrite_text():
    store, plan_set, plan_update, _ = _tools()
    _run(plan_set(["initial scope"]))
    r = _run(plan_update("t1", "in_progress", text="revised scope"))
    assert r["plan"]["tasks"][0]["text"] == "revised scope"


def test_plan_update_rejects_unknown_id():
    store, plan_set, plan_update, _ = _tools()
    _run(plan_set(["A"]))
    assert _run(plan_update("t99", "done"))["error"]


def test_plan_update_rejects_invalid_status():
    store, plan_set, plan_update, _ = _tools()
    _run(plan_set(["A"]))
    assert _run(plan_update("t1", "wibble"))["error"]


def test_plan_update_without_plan_errors_cleanly():
    _, _, plan_update, _ = _tools()
    r = _run(plan_update("t1", "done"))
    assert "error" in r


def test_plan_get_returns_current_plan():
    store, plan_set, _, plan_get = _tools()
    _run(plan_set(["A", "B"]))
    r = _run(plan_get())
    assert r["plan"]["tasks"][0]["text"] == "A"


def test_plan_skill_wires_three_tools():
    store = VariableStore()
    skill = build_plan_skill(store)
    tool_names = {t.name for t in skill.tools}
    assert tool_names == {"plan_set", "plan_update", "plan_get"}
