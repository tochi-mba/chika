"""Tests for plan_add, plan_remove, and the live-checklist invariants."""
from __future__ import annotations

import asyncio

from chika.core.variable_store import VariableStore
from chika.skills.plan_skill import _make_plan_tools


def _build():
    vs = VariableStore()
    # _make_plan_tools now returns 6 callables (plan_edit was added).
    # Tests in this file only need the first five — drop the rest.
    plan_set, plan_update, plan_get, plan_add, plan_remove, *_ = _make_plan_tools(vs)
    return vs, plan_set, plan_update, plan_get, plan_add, plan_remove


def _tasks(plan: dict) -> list[dict]:
    return list(plan["plan"]["tasks"])


def test_plan_add_appends_with_unique_ids():
    vs, plan_set, _, _, plan_add, _ = _build()
    asyncio.run(plan_set(["Read the spec", "Draft the API"]))
    out = asyncio.run(plan_add(["Write tests", "Ship docs"]))
    tasks = _tasks(out)
    assert [t["text"] for t in tasks] == [
        "Read the spec", "Draft the API", "Write tests", "Ship docs",
    ]
    ids = [t["id"] for t in tasks]
    assert len(ids) == len(set(ids)), f"ids should be unique, got {ids!r}"


def test_plan_add_after_id_inserts_in_place():
    vs, plan_set, _, _, plan_add, _ = _build()
    asyncio.run(plan_set(["A", "B", "C"]))
    out = asyncio.run(plan_add(["B.1", "B.2"], after_id="t2"))
    tasks = _tasks(out)
    assert [t["text"] for t in tasks] == ["A", "B", "B.1", "B.2", "C"]


def test_plan_add_unknown_after_id_errors():
    vs, plan_set, _, _, plan_add, _ = _build()
    asyncio.run(plan_set(["A"]))
    out = asyncio.run(plan_add(["B"], after_id="nope"))
    assert "error" in out
    # Plan unchanged
    assert _tasks(asyncio.run(_make_plan_tools(vs)[2]())) == _tasks({
        "plan": vs.get("plan").value,
    })


def test_plan_add_bootstraps_when_no_plan_yet():
    """plan_add called with no existing plan should set the plan, not error."""
    vs, _, _, _, plan_add, _ = _build()
    out = asyncio.run(plan_add(["Lonely first task"]))
    assert "error" not in out
    tasks = _tasks(out)
    assert len(tasks) == 1
    assert tasks[0]["text"] == "Lonely first task"


def test_plan_remove_drops_specified_ids():
    vs, plan_set, _, _, _, plan_remove = _build()
    asyncio.run(plan_set(["A", "B", "C"]))
    out = asyncio.run(plan_remove(["t1", "t3"]))
    assert out["removed"] == ["t1", "t3"]
    tasks = _tasks(out)
    assert [t["text"] for t in tasks] == ["B"]


def test_plan_remove_accepts_single_id_string():
    vs, plan_set, _, _, _, plan_remove = _build()
    asyncio.run(plan_set(["A", "B"]))
    out = asyncio.run(plan_remove("t1"))
    assert out["removed"] == ["t1"]
    assert [t["text"] for t in _tasks(out)] == ["B"]


def test_plan_remove_reports_unknown_ids():
    vs, plan_set, _, _, _, plan_remove = _build()
    asyncio.run(plan_set(["A"]))
    out = asyncio.run(plan_remove(["t1", "tZ", "tQ"]))
    assert out["removed"] == ["t1"]
    assert sorted(out["not_found"]) == ["tQ", "tZ"]


def test_plan_remove_promotes_next_pending_when_inprogress_dropped():
    vs, plan_set, _, _, _, plan_remove = _build()
    asyncio.run(plan_set(["A", "B", "C"]))
    # plan_set auto-promotes t1 to in_progress; remove it
    out = asyncio.run(plan_remove(["t1"]))
    tasks = _tasks(out)
    # t2 (now first) should be in_progress
    assert tasks[0]["id"] == "t2"
    assert tasks[0]["status"] == "in_progress"


def test_full_lifecycle_set_add_update_remove():
    """End-to-end: set → add → update → remove → final state."""
    vs, plan_set, plan_update, plan_get, plan_add, plan_remove = _build()
    asyncio.run(plan_set(["Spec", "Build", "Ship"]))
    asyncio.run(plan_add(["Doc"], after_id="t2"))
    asyncio.run(plan_update("t1", status="done"))
    asyncio.run(plan_remove(["t1"]))

    final = asyncio.run(plan_get())
    tasks = final["plan"]["tasks"]
    texts = [t["text"] for t in tasks]
    assert texts == ["Build", "Doc", "Ship"]
    # Build should be in_progress (was promoted by plan_update auto-promote)
    by_text = {t["text"]: t for t in tasks}
    assert by_text["Build"]["status"] == "in_progress"
